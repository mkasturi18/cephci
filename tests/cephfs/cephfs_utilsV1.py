"""
This is cephfs utility module
It contains all the re-useable functions related to cephfs
It installs all the pre-requisites on client nodes

"""
import json
import logging

log = logging.getLogger(__name__)


class FsUtils(object):
    def __init__(self, ceph_cluster):
        """
        FS Utility object
        Args:
            ceph_cluster (ceph.ceph.Ceph): ceph cluster
        """
        self.ceph_cluster = ceph_cluster

    def prepare_clients(self, clients, build):
        """
        Installs all the required rpms and clones the tools required for running Tests on clients
        Args:
            clients:
            build:
        Returns:

        """
        for client in clients:
            pkgs = [
                "python3",
                "python3-pip",
                "fio",
                "fuse",
                "ceph-fuse",
                "attr",
                "gcc",
                "python3-devel",
            ]
            if build.endswith("7") or build.startswith("3"):
                pkgs.extend(
                    [
                        "@development",
                        "rh-python36",
                        "rh-python36-numpy rh-python36-scipy",
                        "rh-test-python-tools rh-python36-python-six",
                        "libffi libffi-devel",
                    ]
                )
            cmd = "yum install -y --nogpgcheck " + " ".join(pkgs)
            client.node.exec_command(sudo=True, cmd=cmd, long_running=True)
            client.node.exec_command(
                sudo=True, cmd="pip3 install xattr", long_running=True
            )
            out, rc = client.node.exec_command(sudo=True, cmd="ls /home/cephuser")
            output = out.read().decode()
            output.split()
            if "smallfile" not in output:
                client.node.exec_command(
                    cmd="git clone https://github.com/bengland2/smallfile.git"
                )

    @staticmethod
    def get_fs_info(client, fs_name="cephfs"):
        """
        Gets the fs info for the given filesystem.
        if fs_name not given.it fetches the default cephfs info
        Args:
            client:
            fs_name:

        Returns:
            dictonary with fs_name, metadata_pool,data_pool
        """
        out, rc = client.exec_command(sudo=True, cmd="ceph fs ls --format json-pretty")
        all_fs_info = json.loads(out.read().decode())
        output_dict = {}
        for fs in all_fs_info:
            if fs_name == fs["name"]:
                output_dict["fs_name"] = fs["name"]
                output_dict["metadata_pool_name"] = fs["metadata_pool"]
                output_dict["data_pool_name"] = fs["data_pools"][0]
        return output_dict

    def auth_list(self, clients, **kwargs):
        """
        Creates ceph.client.<hostname>.keyring file for the given clients
        Args:
            clients:
            **kwargs:

        Returns:

        """
        fs_info = self.get_fs_info(clients[0])
        for client in clients:
            log.info("Giving required permissions for clients:")
            client.exec_command(
                sudo=True,
                cmd=f"ceph auth get-or-create client.{client.node.hostname}"
                f" mon 'allow *' mds "
                f"'allow *, allow * path=/' osd 'allow "
                f"rw pool={fs_info.get('data_pool_name')}'"
                f" -o /etc/ceph/ceph.client.{client.node.hostname}.keyring",
            )
            client.exec_command(
                sudo=True,
                cmd=f"chmod 644 /etc/ceph/ceph.client.{client.node.hostname}.keyring",
            )

    def fuse_mount(self, fuse_clients, mounting_dir, **kwargs):
        """
        Mounts the drive using Fuse mount
        Args:
            fuse_clients:
            mounting_dir:
            **kwargs:
                extra_params : we can include extra parameters that needs to be passed to ceph fs fuse mount
        Returns:

        Exceptions:
            assertion error will occur if the device is not mounted
        """
        for client in fuse_clients:
            log.info("Creating mounting dir:")
            client.exec_command(sudo=True, cmd="mkdir %s" % mounting_dir)
            log.info("Mounting fs with ceph-fuse on client %s:" % client.node.hostname)
            fuse_cmd = f"ceph-fuse -n client.{kwargs.get('new_client_hostname', client.node.hostname)} {mounting_dir} "
            if kwargs.get("extra_params"):
                fuse_cmd += f"{kwargs.get('extra_params')}"
            client.exec_command(sudo=True, cmd=fuse_cmd)
            out, rc = client.exec_command(cmd="mount")
            mount_output = out.read().decode().rstrip("\n")
            mount_output = mount_output.split()
            log.info("Checking if fuse mount is is passed of failed:")
            assert mounting_dir.rstrip("/") in mount_output, "Fuse mount failed"

    def kernel_mount(self, kernel_clients, mounting_dir, mon_node_ip, **kwargs):
        """
        Mounts the drive using kernel mount
        Args:
            kernel_clients:
            mounting_dir:
            mon_node_ip:
            **kwargs:
                extra_params : we can include extra parameters that needs to be passed to ceph fs fuse mount
        Returns:

        Exceptions:
            assertion error will occur if the device is not mounted
        """
        for client in kernel_clients:
            log.info("Creating mounting dir:")
            client.exec_command(sudo=True, cmd="mkdir %s" % mounting_dir)
            out, rc = client.exec_command(
                sudo=True,
                cmd=f"ceph auth get-key client.{kwargs.get('new_client_hostname', client.node.hostname)} -o "
                f"/etc/ceph/{kwargs.get('new_client_hostname', client.node.hostname)}.secret",
            )

            kernel_cmd = (
                f"mount -t ceph {mon_node_ip}:/ {mounting_dir} "
                f"-o name={kwargs.get('new_client_hostname', client.node.hostname)},"
                f"secretfile=/etc/ceph/{kwargs.get('new_client_hostname', client.node.hostname)}.secret"
            )

            if kwargs.get("extra_params"):
                kernel_cmd += f"{kwargs.get('extra_params')}"
            client.exec_command(
                sudo=True,
                cmd=kernel_cmd,
            )
            out, rc = client.exec_command(cmd="mount")
            mount_output = out.read().decode()
            mount_output = mount_output.split()
            log.info("Checking if kernel mount is is passed of failed:")
            assert mounting_dir.rstrip("/") in mount_output, "Kernel mount failed"

    def get_mon_node_ips(self):
        """
        Returns:
            All the mon ips as a list
        """
        return [node.ip_address for node in self.ceph_cluster.get_nodes(role="mon")]

    @staticmethod
    def client_clean_up(fuse_clients, kernel_clients, mounting_dir, *args, **kwargs):
        """
        This method cleans up all the client nodes and mount points
        Args:
            fuse_clients:
            kernel_clients:
            mounting_dir:
            *args:
                umount : if this argument is passed this will unmounts all the devices
            **kwargs:

        Returns:
            0 if all the clean up is passed
        """
        clients = fuse_clients + kernel_clients
        for client in clients:
            log.info("Removing files:")
            client.exec_command(
                sudo=True,
                cmd=f"rm -rf {mounting_dir}/*",
                long_running=True,
                timeout=3600,
            )

            if "umount" in args:
                if client in fuse_clients:
                    log.info("Unmounting fuse client:")
                    cmd = f"fusermount -u {mounting_dir} -z"
                else:
                    log.info("Unmounting Kernel client:")
                    cmd = f"umount {mounting_dir} -l"
                client.exec_command(sudo=True, cmd=cmd)
                log.info("Removing mounting directory:")
                client.exec_command(sudo=True, cmd=f"rmdir {mounting_dir}")
                log.info("Removing keyring file:")
                client.exec_command(
                    sudo=True,
                    cmd=f"rm -rf /etc/ceph/ceph.client.{kwargs.get('client_name', client.node.hostname)}.keyring",
                )
                log.info("Removing permissions:")
                client.exec_command(
                    sudo=True,
                    cmd=f"ceph auth del client.{kwargs.get('client_name', client.node.hostname)}",
                )
                client.exec_command(
                    cmd="find /home/cephuser -type f -not -name 'authorized_keys' "
                    " -name 'Crefi' -name 'smallfile' -delete",
                    long_running=True,
                    timeout=3600,
                )
                client.exec_command(
                    cmd="cd /home/cephuser && ls -a | grep -v 'authorized_keys' |"
                    "xargs sudo rm -f",
                    long_running=True,
                    timeout=3600,
                )
                client.exec_command(sudo=True, cmd="iptables -F", check_ec=False)

        return 0
