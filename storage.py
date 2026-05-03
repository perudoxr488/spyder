import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    data_dir = (
        os.environ.get("SPIDERSYN_DATA_DIR")
        or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        or BASE_DIR
    )
    data_dir = os.path.abspath(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def db_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)
