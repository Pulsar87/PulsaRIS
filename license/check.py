import hashlib
import os
import platform
import subprocess
from datetime import datetime

SECRET_SALT = "Pul$@r_Security_SALT"


def get_hardware_id():
    """Combines Motherboard and Hard Disk IDs for a stronger lock."""
    system = platform.system()
    board_id = ""
    disk_id = ""

    # Get Motherboard ID
    try:
        if system == "Windows":
            board_id = (
                subprocess.check_output("wmic baseboard get serialnumber", shell=True)
                .decode()
                .split("\n")[1]
                .strip()
            )
        elif system == "Linux":
            board_id = (
                open("/etc/machine-id").read().strip()
                if os.path.exists("/etc/machine-id")
                else "LINUX-BOARD"
            )
        elif system == "Darwin":
            cmd = "ioreg -l | grep IOPlatformSerialNumber"
            board_id = (
                subprocess.check_output(cmd, shell=True)
                .decode()
                .split("=")[-1]
                .replace('"', "")
                .strip()
            )
    except:
        board_id = "BOARD-UNAVAILABLE"

    # Get Disk ID
    try:
        if system == "Windows":
            disk_id = (
                subprocess.check_output("wmic diskdrive get serialnumber", shell=True)
                .decode()
                .split("\n")[1]
                .strip()
            )
        elif system == "Linux":
            disk_id = (
                subprocess.check_output("lsblk -no SERIAL /dev/sda", shell=True)
                .decode()
                .strip()
            )
        elif system == "Darwin":
            cmd = "system_profiler SPStorageDataType | grep 'Serial Number' | head -n 1"
            disk_id = (
                subprocess.check_output(cmd, shell=True).decode().split(":")[-1].strip()
            )
    except:
        disk_id = "DISK-UNAVAILABLE"

    combined = f"{board_id}|{disk_id}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16].upper()


def verify_key(provided_key):
    """Verifies Board ID + Disk ID + Expiration Date."""
    try:
        if "-" not in provided_key:
            return False

        expiry_str, signature = provided_key.split("-")
        expiry_date = datetime.strptime(expiry_str, "%d%m%y")

        # 1. Date Check
        if datetime.now() > expiry_date:
            return False

        # 2. Hardware + Date Signature Check
        hwid = get_hardware_id()  # This now includes the Disk ID
        expected_data = f"{hwid}|{expiry_str}|{SECRET_SALT}"
        expected_sig = hashlib.sha256(expected_data.encode()).hexdigest()[:8].upper()

        return signature == expected_sig
    except:
        return False
