import os

def workon(uid, oncreate, oncomplete):
    ## uid: str
    ## oncreate: uid -> (query, serializable data)
    ## oncomplete: (uid, serializable data) -> None

    # First, check if we are waiting on a result for uid
    local_status = check_local_status(uid)
    if local_status == "submitted":
        # If so, see if we now have a result
        remote_status = check_remote_status(uid)
        # Handle case where waited too long, or it expired/errored -- start over
        # If we have result, call oncomplete
        TODO
    elif local_status == "missing":
        # If we have not submitted uid yet, submit it
        TODO
    else:
        raise RuntimeError("Unknown local status")

def check_local_status(uid):
    logpath = os.path.join("batches", uid + ".log")
    if os.path.exists(logpath):
        with open(logpath, 'r') as fp:
            return fp.read()

    return "missing"
