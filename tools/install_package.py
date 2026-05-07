#!/usr/bin/env python3

import subprocess
import os
import logging

# Configure basic logging to see output in the agent's logs
# In a real scenario, this might integrate with a more robust logging system
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

def install_package(package_name: str) -> str:
    """
    Installs a specified package on the VPS using apt or yum/dnf.
    Requires sudo privileges.
    """
    log.info(f"Attempting to install package: {package_name}")

    # Check for package manager
    pkg_manager = None
    update_cmd = None
    install_cmd_template = None

    if os.path.exists("/usr/bin/apt"):
        pkg_manager = "apt"
        update_cmd = "sudo apt update -y"
        install_cmd_template = "sudo apt install -y {package}"
    elif os.path.exists("/usr/bin/dnf"):
        pkg_manager = "dnf"
        update_cmd = "sudo dnf check-update" # dnf update -y might be too aggressive, better to check first
        install_cmd_template = "sudo dnf install -y {package}"
    elif os.path.exists("/usr/bin/yum"):
        pkg_manager = "yum"
        update_cmd = "sudo yum check-update" # yum update -y might be too aggressive
        install_cmd_template = "sudo yum install -y {package}"
    else:
        return "Error: No supported package manager (apt, dnf, yum) found on the system."

    # Update package list first
    log.info(f"Running package list update command: {update_cmd}")
    try:
        # Using default run_shell function
        update_result_dict = default_api.run_shell(command=update_cmd, timeout=120)
        if "error" in update_result_dict and update_result_dict["error"]: # Assuming run_shell returns a dict with 'error' key for errors
            log.error(f"Failed to update package list: {update_result_dict['error']}")
            return f"Error updating package list with '{pkg_manager}'. Details: {update_result_dict['error']}"
        log.info(f"Package list update successful. Output: {update_result_dict.get('output', '')[:200]}...") # Log partial output

    except Exception as e:
        log.error(f"An unexpected error occurred during package list update: {e}")
        return f"An unexpected error occurred during package list update: {e}"


    # Install the package
    install_cmd = install_cmd_template.format(package=package_name)
    log.info(f"Running install command: {install_cmd}")
    try:
        install_result_dict = default_api.run_shell(command=install_cmd, timeout=300) # 5 minutes timeout for installation

        if "error" in install_result_dict and install_result_dict["error"]:
            log.error(f"Failed to install package '{package_name}'. Details: {install_result_dict['error']}")
            # Try to provide a more specific error message if possible
            error_msg = install_result_dict['error'].lower()
            if "unable to locate package" in error_msg or "no match for argument" in error_msg:
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
