from ceph.parallel import parallel
from ceph.rbd.utils import getdict
from ceph.rbd.workflows.pool import create_ecpool, create_pool
from utility.log import Log

log = Log(__name__)


def create_snap_and_clone(rbd, snap_spec, clone_spec, **kw):
    """_summary_

    Args:
        snap_spec (_type_): _description_
        clone_spec (_type_): _description_
    """
    snap_config = {"snap-spec": snap_spec}

    out, err = rbd.snap.create(**snap_config)
    if out or err and "100% complete" not in err:
        log.error(f"Snapshot creation failed for {snap_spec}")
        return 1

    out, err = rbd.snap.protect(**snap_config)
    if out or err:
        log.error(f"Snapshot protect failed for {snap_spec}")
        return 1

    clone_config = {"source-snap-spec": snap_spec, "dest-image-spec": clone_spec}
    if kw.get("clone_format"):
        clone_config.update({"rbd-default-clone-format": kw.get("clone_format")})

    out, err = rbd.clone(**clone_config)
    if out or err:
        log.error(f"Clone creation failed for {clone_spec}")
        return 1

    return 0


def create_single_image(
    config,
    cluster,
    rbd,
    pool,
    pool_config,
    image,
    image_config_val,
    is_ec_pool,
    raise_exception=False,
):
    """
    Method to create single image
    """
    if not config.get("do_not_create_image"):
        create_config = {"pool": pool, "image": image}
        if is_ec_pool:
            create_config.update({"data-pool": pool_config.get("data_pool")})
        # Update any other specific arguments that rbd create command takes if passed in config
        create_config.update(
            {
                k: v
                for k, v in image_config_val.items()
                if k
                not in [
                    "io_total",
                    "test_config",
                    "is_secondary",
                    "snap_schedule_levels",
                    "snap_schedule_intervals",
                    "io_size",
                ]
            }
        )
        create_config.update({"cluster": cluster})
        out, err = rbd.create(**create_config)
        if out or err:
            log.error(f"Image {image} creation failed with err {out} {err}")
            if raise_exception:
                raise Exception(f"Image {image} creation failed with err {out} {err}")
            return 1
    return 0


def create_images(
    config,
    cluster,
    rbd,
    pool,
    pool_config,
    image_config,
    is_ec_pool,
    create_image_parallely,
):
    """
    Method to create multiple images parallely/sequentially
    """
    if not create_image_parallely:
        for image, image_config_val in image_config.items():
            rc = create_single_image(
                config,
                cluster,
                rbd,
                pool,
                pool_config,
                image,
                image_config_val,
                is_ec_pool,
            )
            if rc:
                return rc
    else:
        try:
            with parallel() as p:
                for image, image_config_val in image_config.items():
                    p.spawn(
                        create_single_image,
                        config,
                        cluster,
                        rbd,
                        pool,
                        pool_config,
                        image,
                        image_config_val,
                        is_ec_pool,
                        raise_exception=True,
                    )
        except Exception:
            return 1
    return 0


def create_single_pool_and_images(
    config,
    pool,
    pool_config,
    client,
    cluster,
    rbd,
    ceph_version,
    is_ec_pool,
    is_secondary,
    create_image_parallely,
    raise_exception=False,
):
    """
    Method to create a single pool
    """
    if create_pool(
        pool=pool,
        pg_num=pool_config.get("pg_num", 64),
        pgp_num=pool_config.get("pgp_num", 64),
        client=client,
        cluster=cluster,
    ):
        log.error(f"Pool creation failed for pool {pool}")
        if raise_exception:
            raise Exception(f"Pool creation failed for pool {pool}")
        return 1

    if ceph_version >= 3:
        pool_init_conf = {"pool-name": pool, "cluster": cluster}
        rbd.pool.init(**pool_init_conf)

    if is_ec_pool and create_ecpool(
        pool=pool_config.get("data_pool"),
        k_m=pool_config.get("ec-pool-k-m"),
        profile=pool_config.get("ec_profile", "use_default"),
        pg_num=pool_config.get("ec_pg_num", 32),
        pgp_num=pool_config.get("ec_pgp_num", 32),
        failure_domain=pool_config.get("failure_domain", ""),
        client=client,
        cluster=cluster,
    ):
        log.error(f"EC Pool creation failed for {pool_config.get('data_pool')}")
        if raise_exception:
            raise Exception(
                f"EC Pool creation failed for {pool_config.get('data_pool')}"
            )
        return 1

    if is_ec_pool and ceph_version >= 3:
        pool_init_conf = {
            "pool-name": pool_config.get("data_pool"),
            "cluster": cluster,
        }
        rbd.pool.init(**pool_init_conf)

    multi_image_config = getdict(pool_config)
    image_config = {
        k: v
        for k, v in multi_image_config.items()
        if v.get("is_secondary", False) == is_secondary
    }
    rc = create_images(
        config,
        cluster,
        rbd,
        pool,
        pool_config,
        image_config,
        is_ec_pool,
        create_image_parallely,
    )
    if rc:
        log.error(f"Error while creating images for pool {pool}")
        if raise_exception:
            raise Exception(f"Error while creating images for pool {pool}")
        return 1
    return 0


def create_pools_and_images(
    rbd,
    multi_pool_config,
    is_ec_pool,
    ceph_version,
    config,
    client,
    is_secondary=False,
    cluster="ceph",
    create_pool_parallely=False,
    create_image_parallely=False,
):
    """
    Create number of pools as specified in parallel/sequential
    """

    # If any pool level test config is present, pop it out
    # so that it does not get mistaken as another image configuration
    pool_test_config = multi_pool_config.pop("test_config", None)

    if not create_pool_parallely:
        for pool, pool_config in multi_pool_config.items():
            rc = create_single_pool_and_images(
                config,
                pool,
                pool_config,
                client,
                cluster,
                rbd,
                ceph_version,
                is_ec_pool,
                is_secondary,
                create_image_parallely,
            )
            if rc:
                return rc
    else:
        try:
            with parallel() as p:
                for pool, pool_config in multi_pool_config.items():
                    p.spawn(
                        create_single_pool_and_images,
                        config,
                        pool,
                        pool_config,
                        client,
                        cluster,
                        rbd,
                        ceph_version,
                        is_ec_pool,
                        is_secondary,
                        create_image_parallely,
                        raise_exception=True,
                    )
        except Exception:
            return 1

    # Add back the popped pool test config once configuration is complete
    if pool_test_config:
        multi_pool_config["test_config"] = pool_test_config

    if rc:
        log.error("Multi pool and multi image config failed")
        return rc
    return 0
