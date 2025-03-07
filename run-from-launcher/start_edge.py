#!/usr/bin/env python3
import subprocess
import time
import sys
import signal
import threading
import requests
import re
import os

DOCKER_DIR = "/home/skdj/Pysolated/penv_msedge/"

def force_zenity_on_top(delay=0.5, retries=10):
    """Poll for the Zenity window until found, then force it on top."""
    for _ in range(retries):
        result = subprocess.run(["wmctrl", "-x", "-r", "zenity.zenity", "-b", "add,above"])
        if result.returncode == 0:
            return True
        time.sleep(delay)
    return False

def get_sudo_password():
    global SUDO_PWD
    # Start a background thread to force the Zenity window on top.
    threading.Thread(target=force_zenity_on_top, args=(0.5, 20), daemon=True).start()
    try:
        SUDO_PWD = subprocess.check_output(
            ["zenity", "--password", "--title=Enter Sudo Password"],
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        print("Failed to get sudo password via Zenity.")
        sys.exit(1)

def start_loading_animation():
    # Start a background thread to force the Zenity window on top.
    threading.Thread(target=force_zenity_on_top, args=(0.5, 20), daemon=True).start()
    """
    Launch a Zenity progress dialog with a pulsating progress bar.
    Returns the process handle.
    """
    anim = subprocess.Popen(
        ["zenity", "--progress", "--pulsate", "--no-cancel",  "--auto-close", "--text=Starting..."],
        stdin=subprocess.PIPE,
        text=True
    )
    return anim
    
def stop_loading_animation(anim):
    """
    Terminates the Zenity progress dialog given its process handle.
    """
    anim.terminate()
    anim.wait()

def run_docker_command(cmd, cwd=None, capture_output=False):
    global SUDO_PWD
    docker_cmd = ["sudo", "-S"] + cmd
    try:
        result = subprocess.run(docker_cmd, cwd=cwd, check=True, capture_output=capture_output, text=True, input=SUDO_PWD+"\n")
        if capture_output:
            return result.stdout.strip()
    except subprocess.CalledProcessError:
        print(f"Error running command: {' '.join(docker_cmd)}")
        sys.exit(1)

def shutdown_container():
    print("Shutting down container and removing orphans...")
    run_docker_command(["docker-compose", "down", "-v", "--remove-orphans"], cwd=DOCKER_DIR)

def cleanup(signum, frame):
    print("\nReceived termination signal. Cleaning up...")
    shutdown_container()
    sys.exit(0)

def check_for_update():
    url = "https://api.github.com/repos/linuxserver/docker-msedge/releases/latest"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            release = response.json()
            tag = release.get("tag_name", "unknown")
            changelog = release.get("body", "")
            return tag, changelog
        else:
            print("Could not fetch release info (status code:", response.status_code, ")")
    except Exception as e:
        print("Error fetching release info:", e)
    return None, None

def ask_user_for_update():
    """
    Stops the current spinner, prompts the user to update,
    then restarts the spinner (with new text) regardless of the answer.
    Returns a tuple: (update_choice, new_proc)
    """
    stop_loading_animation(spinner)
    # Use Zenity to prompt the user.
    # Start a background thread to force the Zenity window on top.
    threading.Thread(target=force_zenity_on_top, args=(0.5, 20), daemon=True).start()
    result = subprocess.call([
        "zenity", "--question",
        "--text=Do you want to update the image?",
        "--title=Update Image"
    ])
    # Restart the spinner regardless of the result:
    # Start a background thread to force the Zenity window on top.
    threading.Thread(target=force_zenity_on_top, args=(0.5, 20), daemon=True).start()
    spinner = start_loading_animation()
    return result == 0, spinner

def update_image():
    spinner.stdin.write("#Updating MS siolation\n")
    spinner.stdin.flush()
    print("Pulling the latest image...")
    run_docker_command(["docker-compose", "pull", "edge"], cwd=DOCKER_DIR)
    print("Restarting container with new image...")
    run_docker_command(["docker-compose", "up", "-d"], cwd=DOCKER_DIR)
    print("Update complete. Exiting terminal.")
    sys.exit(0)

def get_current_image_version():
    try:
        output = run_docker_command(
            ["docker", "inspect", "--format", "{{ index .Config.Labels \"org.opencontainers.image.version\" }}", "lscr.io/linuxserver/msedge:latest"],
            capture_output=True
        )
        return output.strip()
    except Exception as e:
        print("Error retrieving current image version:", e)
        return None

# Wait for an accepted connection and extract its unique connection string
def get_unique_connection(timeout=15):
    start_time = time.time()
    while time.time() - start_time < timeout:
        logs = run_docker_command(["docker", "logs", "msedge"], capture_output=True)
        match = re.search(r'accepted: @(.*)::websocket', logs)
        if match:
            return match.group(1)
        time.sleep(2)
    return None

def monitor_disconnect(unique):
    # Build the disconnect regex using the unique connection string.
    d = re.compile(r'closed: @' + unique)
    print("Monitoring...")

    # Start following the logs of the 'msedge' container.
    proc = subprocess.Popen(['sudo','docker','logs','-f','msedge'], stdout=subprocess.PIPE, text=True)

    while True:
        line = proc.stdout.readline()
        if d.search(line):
            print("Disconnect detected.")
            # Prompt the user to shut down the container.
            # Start a background thread to force the Zenity window on top.
            threading.Thread(target=force_zenity_on_top, args=(0.5, 20), daemon=True).start()
            result = subprocess.call([
                "zenity", "--question",
                "--text=The disconnect event was detected.\nDo you want to shut down the container now?",
                "--title=Shutdown Container"
            ])
            if result == 0:
                # Attempt shutdown without sudo first.
                try:
                    print("Attempting shutdown without sudo...")
                    subprocess.run(["docker-compose", "down", "-v", "--remove-orphans"], check=True)
                except subprocess.CalledProcessError:
                    print("Shutdown without sudo failed; using stored sudo password...")
                    subprocess.run(["sudo", "-S", "docker-compose", "down", "-v", "--remove-orphans"], 
                                   input=SUDO_PWD+"\n", text=True)
                sys.exit(0)
            else:
                print("User canceled shutdown; container will remain running.")
                break  # or continue monitoring if desired.
        time.sleep(1)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    print(f"Changing to Docker directory: {DOCKER_DIR}")

    # Prompt for sudo password at startup.
    get_sudo_password()

    # Start the loading animation right after password acceptance.
    spinner = start_loading_animation()
    force_zenity_on_top()
        
    print("Checking for updates from GitHub...")
    tag, changelog = check_for_update()
    if tag:
        print(f"\nLatest release: {tag}\n")
        print("Changelog:")
        print(changelog)
        print("\n")
        current_version = get_current_image_version()
        if current_version:
            print(f"Current local image version: {current_version}")
        else:
            print("Could not determine local image version.")
        if not current_version or current_version != tag:
            if ask_user_for_update():
                update_image()
                print("Update complete. Continuing to launch Vivaldi...")
            else:
                print("Update cancelled. Continuing with current image...")
    else:
        print("No update information available. Continuing with current image...")

    spinner.stdin.write("#Preparing environment\n")
    spinner.stdin.flush()
    
    print("Stopping any existing container instance...")
    run_docker_command(["docker-compose", "down", "-v", "--remove-orphans"], cwd=DOCKER_DIR)
    
    print("Starting container...")
    run_docker_command(["docker-compose", "up", "-d"], cwd=DOCKER_DIR)

    spinner.stdin.write("#Isolating Microsoft on Ubuntu\n")
    spinner.stdin.flush()
    
    print("Waiting for container to initialize...")
    time.sleep(5)
    
    print("Current running Docker containers:")
    docker_ps = run_docker_command(["docker", "ps"], capture_output=True)
    print(docker_ps)
    
    print("Launching Vivaldi in app mode...")
    vivaldi_cmd = ["flatpak", "run", "com.vivaldi.Vivaldi", "--app=http://localhost:3000"]
    print(f"Launching Vivaldi with command: {' '.join(vivaldi_cmd)}")
    try:
        subprocess.Popen(vivaldi_cmd)
        stop_loading_animation(spinner)
    except FileNotFoundError:
        print("Error: Vivaldi (Flatpak) is not installed or not found in PATH.")
        shutdown_container()
        sys.exit(1)
    
    # Wait for the accepted connection to be logged
    unique = get_unique_connection()
    if unique:
        print("Unique connection string:", unique)
    else:
        print("No accepted connection found within timeout.")
    
    # Continue with the rest of your monitoring or shutdown logic...
    # For demonstration, just echo the unique value.
    print("Echoing UNIQUE:", unique)
    
    # Retrieve the unique connection string from the environment.
    # unique = os.environ.get('UNIQUE')
    # if not unique:
    #    print("Error: UNIQUE is not set.")
    #    sys.exit(1)
        
    # Now start monitoring for the disconnect event using the unique string.
    monitor_disconnect(unique)


if __name__ == "__main__":
    main()
