from tests.rbd.exceptions import ImageFoundError, ImageNotFoundError, RbdBaseException
from tests.rbd.rbd_utils import Rbd
from utility.log import Log
from utility.utils import run_fio

log = Log(__name__)


def run(**kw):
    """Verify the trash restore functionality .

    This module verifies trash operations and does restore and validate

    Args:
        kw: test data

    Returns:
        int: The return value. 0 for success, 1 otherwise

    Pre-requisites :
    We need atleast one client node with ceph-common package,
    conf and keyring files

    Test cases covered -
    1) CEPH-83573298 - Move images to trash, restore them and verify
    Test Case Flow
    1. Create a pool and an Image
    2. generate IO in images
    3. Move the images to trash and check whether images are in trash or not
    4. Undo images from trash and check the image info.

    """
    log.info("Running Trash function")
    rbd = Rbd(**kw)
    pool = rbd.random_string()
    image = rbd.random_string()
    size = "10G"

    try:
        if not rbd.create_pool(poolname=pool):
            # create pool does not catch exceptions, it returns true/false.
            # so we are returning 1 instead of raising exception
            return 1

        rbd.create_image(pool_name=pool, image_name=image, size=size)
        client = kw["ceph_cluster"].get_nodes(role="client")[0]
        run_fio(image_name=image, pool_name=pool, client_node=client)
        cmd = "ceph config set client rbd_move_to_trash_on_remove true"
        rbd.exec_cmd(cmd=cmd)
        rbd.remove_image(pool, image)
        if not rbd.trash_exist(pool, image):
            raise ImageNotFoundError(" Deleted Image not found in the Trash")
        image_id = rbd.get_image_id(pool, image)
        log.info(f"image id is {image_id}")
        rbd.trash_restore(pool, image_id)
        if rbd.trash_exist(pool, image):
            raise ImageFoundError("Restored image found in the Trash")

        return 0

    except RbdBaseException as error:
        print(error.message)
        return 1

    finally:
        rbd.clean_up(pools=[pool])
