import base64
import io
import json
import os
import random
import string
import subprocess
import sys
import tarfile
from collections import OrderedDict
from typing import Any, Dict

from .. import logger
from . import gzip_compress_bytes
from .aws import clients, ensure_s3_bucket
from .crypto import get_public_key_from_pair


def add_file_to_cloudinit_manifest(src_path, path, manifest):
    with open(src_path, "rb") as fh:
        content = fh.read()
        manifest[path] = dict(path=path, permissions='0' + oct(os.stat(src_path).st_mode)[-3:])
        try:
            manifest[path].update(content=content.decode())
        except UnicodeDecodeError:
            manifest[path].update(content=base64.b64encode(gzip_compress_bytes(content)), encoding="gz+b64")

def get_rootfs_skel_dirs(args):
    # Build a list of rootfs_skel_dirs to build from. The arg element 'auto' is
    # expanded to the default aegea skel as well as rootfs.skel.<command> directories in
    # the same paths as config files.
    rootfs_skel_dirs = OrderedDict()  # type: OrderedDict[str, None]
    for arg in args.rootfs_skel_dirs:
        if arg == 'auto':
            from .. import config
            dirs_to_scan = [os.path.dirname(p) for p in config.config_files]
            for path in dirs_to_scan:
                path = os.path.join(os.path.expanduser(path), "rootfs.skel." + args.entry_point.__name__)
                if os.path.isdir(path):
                    rootfs_skel_dirs[path] = None
        else:
            rootfs_skel_dirs[os.path.expanduser(arg)] = None
    if rootfs_skel_dirs:
        logger.info('Adding rootfs skel files from these paths: %s', ', '.join(rootfs_skel_dirs))
    else:
        logger.debug('No rootfs skel files.')
    return list(rootfs_skel_dirs)

def get_bootstrap_files(rootfs_skel_dirs, dest="cloudinit"):
    manifest = OrderedDict()  # type: OrderedDict[str, Dict]
    targz = io.BytesIO()
    tar = tarfile.open(mode="w:gz", fileobj=targz) if dest == "tarfile" else None
    for rootfs_skel_dir in rootfs_skel_dirs:
        if os.path.exists(rootfs_skel_dir):
            rootfs_skel_dir = os.path.abspath(os.path.normpath(rootfs_skel_dir))
        else:
            raise Exception("rootfs_skel directory {} not found".format(rootfs_skel_dir))
        logger.debug("Trying rootfs.skel: %s" % rootfs_skel_dir)

        for root, dirs, files in os.walk(rootfs_skel_dir):
            for file_ in files:
                path = os.path.join("/", os.path.relpath(root, rootfs_skel_dir), file_)
                if dest == "cloudinit":
                    add_file_to_cloudinit_manifest(os.path.join(root, file_), path, manifest)
                elif dest == "tarfile":
                    tar.add(os.path.join(root, file_), path)

    if dest == "cloudinit":
        return list(manifest.values())
    elif dest == "tarfile":
        tar.close()
        return targz.getvalue()

def get_user_data(host_key=None, commands=None, packages=None, rootfs_skel_dirs=None, storage=None,
                  mime_multipart_archive=False, ssh_ca_keys=None, provision_users=None, **kwargs):
    """
    provision_users can be either a list of Linux usernames or a list of dicts as described in
    https://cloudinit.readthedocs.io/en/latest/topics/modules.html#module-cloudinit.config.cc_users_groups
    """
    cloud_config_data = OrderedDict()  # type: OrderedDict[str, Any]
    cloud_config_data["bootcmd"] = [
        "for d in /dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol?????????????????; do "
        "a=/dev/$(nvme id-ctrl --raw-binary $d 2>/dev/null | dd skip=3072 bs=1 count=4 status=none); "
        "[[ -e $a ]] || ln -s $d $a; "
        "done"
    ]
    for i, (mountpoint, size_gb) in enumerate(storage.items() if storage else []):
        cloud_config_data.setdefault("fs_setup", [])
        cloud_config_data.setdefault("mounts", [])
        device = "/dev/xvd" + chr(ord("z") - i)
        fs_spec = dict(device=device, filesystem="xfs", partition="none")
        cloud_config_data["fs_setup"].append(fs_spec)
        cloud_config_data["mounts"].append([device, mountpoint, "auto", "defaults", "0", "2"])
    cloud_config_data["packages"] = packages or []
    cloud_config_data["runcmd"] = commands or []
    cloud_config_data["write_files"] = get_bootstrap_files(rootfs_skel_dirs or [])
    if ssh_ca_keys:
        cloud_config_data["write_files"] += [dict(path="/etc/ssh/sshd_ca.pem", permissions='0644', content=ssh_ca_keys)]
        cloud_config_data["runcmd"].append("grep -q TrustedUserCAKeys /etc/ssh/sshd_config || "
                                           "(echo 'TrustedUserCAKeys /etc/ssh/sshd_ca.pem' >> /etc/ssh/sshd_config;"
                                           " service sshd reload)")
    if provision_users:
        cloud_config_data["users"] = []
        for user in provision_users:
            if isinstance(user, dict):
                cloud_config_data["users"].append(user)
            else:
                cloud_config_data["users"].append(dict(name=user, gecos="", sudo="ALL=(ALL) NOPASSWD:ALL"))
    for key in sorted(kwargs):
        cloud_config_data[key] = kwargs[key]
    if host_key is not None:
        buf = io.StringIO()
        host_key.write_private_key(buf)
        cloud_config_data["ssh_keys"] = dict(rsa_private=buf.getvalue(),
                                             rsa_public=get_public_key_from_pair(host_key))
    payload = encode_cloud_config_payload(cloud_config_data, mime_multipart_archive=mime_multipart_archive)
    if len(payload) >= 16384:
        logger.warn("Cloud-init payload is too large to be passed in user data, extracting rootfs.skel")
        upload_bootstrap_asset(cloud_config_data, rootfs_skel_dirs)
        payload = encode_cloud_config_payload(cloud_config_data, mime_multipart_archive=mime_multipart_archive)
    return payload

mime_multipart_archive_template = """Content-Type: multipart/mixed; boundary="==BOUNDARY=="
MIME-Version: 1.0

--==BOUNDARY==
Content-Type: text/cloud-config; charset="us-ascii"

{}

--==BOUNDARY==--
"""

def encode_cloud_config_payload(cloud_config_data, mime_multipart_archive=False, gzip=True):
    # TODO: default=dict is for handling tweak.Config objects in the hierarchy.
    # TODO: Should subclass dict, not MutableMapping
    cloud_config_json = json.dumps(cloud_config_data, default=dict)
    if mime_multipart_archive:
        return mime_multipart_archive_template.format(cloud_config_json).encode()
    else:
        slug = "#cloud-config\n" + cloud_config_json
        return gzip_compress_bytes(slug.encode()) if gzip else slug

def upload_bootstrap_asset(cloud_config_data, rootfs_skel_dirs):
    key_name = "".join(random.choice(string.ascii_letters) for x in range(32))
    enc_key = "".join(random.choice(string.ascii_letters) for x in range(32))
    logger.info("Uploading bootstrap asset %s to S3", key_name)
    bucket = ensure_s3_bucket()
    cipher = subprocess.Popen(["openssl", "aes-256-cbc", "-e", "-k", enc_key],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    encrypted_tarfile = cipher.communicate(get_bootstrap_files(rootfs_skel_dirs, dest="tarfile"))[0]
    bucket.upload_fileobj(io.BytesIO(encrypted_tarfile), key_name)
    url = clients.s3.generate_presigned_url(ClientMethod='get_object', Params=dict(Bucket=bucket.name, Key=key_name))
    cmd = "curl -s '{url}' | openssl aes-256-cbc -d -k {key} | tar -xz --no-same-owner -C /"
    cloud_config_data["runcmd"].insert(0, cmd.format(url=url, key=enc_key))
    del cloud_config_data["write_files"]
