"""Check Ceph health and redeploy node-exporter when it is not running."""

import time

from utility.log import Log

LOG = Log(__name__)

NODE_EXPORTER_DOWN_TOKENS = ("unknown", "0/", "Failed to scrape")
MAX_RETRIES = 5
RETRY_SLEEP = 5


def _run_ceph(node, cmd, cephadm=False):
    if cephadm:
        cmd = f"cephadm shell -- {cmd}"
    return node.exec_command(sudo=True, cmd=cmd)


def _node_exporter_not_up(output):
    """Return True if ceph status/health output shows node-exporter is not running."""
    for line in str(output).splitlines():
        if "node-exporter" in line and any(
            token in line for token in NODE_EXPORTER_DOWN_TOKENS
        ):
            return True
    return False


def _node_exporter_unhealthy(status_out, health_out):
    return _node_exporter_not_up(status_out) or "node-exporter" in str(health_out)


def run(ceph_cluster, **kwargs) -> int:
    """
    Run ``ceph -s`` and redeploy node-exporter if it is not up.

    Example::

        - test:
            name: check-ceph-health
            module: ceph_health_check.py
            config:
              cephadm: true
            desc: Check for ceph health debug info
            polarion-id: CEPH-83575200
    """
    config = kwargs.get("config") or {}
    cephadm = config.get("cephadm", False)
    role = "installer" if cephadm else "client"
    nodes = ceph_cluster.get_nodes(role=role)
    if not nodes:
        LOG.error("No %s node found for ceph health check", role)
        return 1
    node = nodes[config.get("idx", 0)]

    try:
        out, _ = _run_ceph(node, "ceph -s", cephadm)
        LOG.info(out)

        health_out, _ = _run_ceph(node, "ceph health detail", cephadm)
        LOG.info(health_out)

        if not _node_exporter_unhealthy(out, health_out):
            LOG.info("Ceph health check passed")
            return 0

        LOG.warning("node-exporter is not up; redeploying node-exporter")
        _run_ceph(node, "ceph orch redeploy node-exporter", cephadm)

        for attempt in range(1, MAX_RETRIES + 1):
            time.sleep(RETRY_SLEEP)
            out, _ = _run_ceph(node, "ceph -s", cephadm)
            LOG.info(out)
            health_out, _ = _run_ceph(node, "ceph health detail", cephadm)
            LOG.info(health_out)
            if not _node_exporter_unhealthy(out, health_out):
                LOG.info(
                    "Ceph health check passed on retry %s/%s",
                    attempt,
                    MAX_RETRIES,
                )
                return 0
            LOG.warning(
                "node-exporter still not up on retry %s/%s",
                attempt,
                MAX_RETRIES,
            )

        LOG.error("node-exporter did not come up after %s retries", MAX_RETRIES)
        return 1
    except BaseException as be:
        LOG.error(be)
        return 1
