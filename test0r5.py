import base64
import copy
import json
import os
import sys
import time
from io import open

from . import __version__, config, logger, register_parser
from .launch import launch
from .launch import parser as launch_parser
from .util.aws import ARN, AegeaException, add_tags, clients, get_bdm, locate_ami, resolve_instance_id, resources
from .util.aws.ssm import run_command
from .util.cloudinit import get_rootfs_skel_dirs
from .util.crypto import ensure_ssh_key, get_ssh_key_path
from .util.printing import GREEN


def build_ami(args):
    if args.name is None:
        args.name = f"aegea-{args.architecture}-{time.strftime('%Y-%m-%d-%H-%M')}"
    for key, value in config.build_image.items():
        getattr(args, key).extend(value)
    if args.instance_type is None:
        args.instance_type = config.build_ami.default_builder_instance_type[args.architecture]
    if args.snapshot_existing_host:
        instance = resources.ec2.Instance(resolve_instance_id(args.snapshot_existing_host))
        args.ami = instance.image_id
    else:
        if args.base_ami == "auto":
            distribution, release = args.base_ami_distribution.split(":", 1)
            args.ami = locate_ami(distribution=distribution, release=release, architecture=args.architecture).id
        else:
            args.ami = args.base_ami
        hostname = f"{__name__}-{args.name}-{int(time.time())}".replace(".", "-").replace("_", "-")
        launch_args = launch_parser.parse_args(args=[hostname], namespace=copy.deepcopy(args))
        launch_args.iam_role = args.iam_role
        launch_args.cloud_config_data.update(rootfs_skel_dirs=get_rootfs_skel_dirs(args))
        instance = resources.ec2.Instance(launch(launch_args)["instance_id"])
    sys.stderr.write(f"Waiting {args.cloud_init_timeout_seconds} seconds for cloud-init ...")
    sys.stderr.flush()

    def wait():
        sys.stderr.write(".")
        sys.stderr.flush()
        time.sleep(args.cloud_init_poll_interval_seconds)

    for i in range(args.cloud_init_timeout_seconds // args.cloud_init_poll_interval_seconds):
        try:
            run_command("sudo jq --exit-status .v1.errors==[] /var/lib/cloud/data/result.json",
                        instance_ids=[instance.id])
            break
        except clients.ssm.exceptions.InvalidInstanceId:
            wait()
        except AegeaException as e:
            if "SSM command failed" in str(e):
                wait()
            else:
                raise
    else:
        raise AegeaException(f"cloud-init encountered errors; please examine and terminate {instance}")
    sys.stderr.write(GREEN("OK") + "\n")
    description = f"Built by {__name__} for {ARN.get_iam_username()}"
    for existing_ami in resources.ec2.images.filter(Owners=["self"], Filters=[{"Name": "name", "Values": [args.name]}]):
        logger.info(f"Deleting existing image {existing_ami}")
        existing_ami.deregister()
    image = instance.create_image(Name=args.name, Description=description, BlockDeviceMappings=get_bdm())
    tags = dict(args.tags)
    base_ami = resources.ec2.Image(args.ami)
    tags.update(Owner=ARN.get_iam_username(), AegeaVersion=__version__,
                Base=base_ami.id, BaseName=base_ami.name, BaseDescription=base_ami.description or "")
    add_tags(image, **tags)
    logger.info("Waiting for %s to become available...", image.id)
    clients.ec2.get_waiter("image_available").wait(ImageIds=[image.id], WaiterConfig=dict(Delay=10, MaxAttempts=120))
    while resources.ec2.Image(image.id).state != "available":
        sys.stderr.write(".")
        sys.stderr.flush()
        time.sleep(1)
    instance.terminate()
    return dict(ImageID=image.id, **tags)

parser = register_parser(build_ami, help="Build an EC2 AMI")
parser.add_argument("name", help="Default: aegea-ARCH-YYYY-MM-DD-HH-MM", nargs="?")
parser.add_argument("--snapshot-existing-host", type=str, metavar="HOST")
parser.add_argument("--wait-for-ami", action="store_true")
parser.add_argument("--ssh-key-name")
parser.add_argument("--no-verify-ssh-key-pem-file", dest="verify_ssh_key_pem_file", action="store_false")
parser.add_argument("--instance-type", default=None,
                    help="Instance type to use for building AMI (default: c5.xlarge for x86_64, c6gd.xlarge for arm64)")
parser.add_argument("--architecture", default="x86_64", choices={"x86_64", "arm64"},
                    help="CPU architecture for building the AMI")
parser.add_argument("--security-groups", nargs="+")
parser.add_argument("--base-ami")
parser.add_argument("--base-ami-distribution",
                    help="Use AMI for this distribution (examples: Ubuntu:20.04, Amazon Linux:2")
parser.add_argument("--dry-run", "--dryrun", action="store_true")
parser.add_argument("--tags", nargs="+", metavar="NAME=VALUE", type=lambda x: x.split("=", 1),
                    help="Tag the resulting AMI with these tags")
parser.add_argument("--cloud-config-data", type=json.loads)
parser.add_argument("--cloud-init-timeout-seconds", type=int,
                    help="Approximate time in seconds to wait for cloud-init to finish before aborting.")
parser.add_argument("--iam-role", default=__name__)
