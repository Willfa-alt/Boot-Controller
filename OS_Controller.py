import os
from time import sleep
import re
import subprocess
import sys
import logging
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QListWidget, QPushButton,
    QMessageBox, QLabel, QHBoxLayout, QListWidgetItem, QInputDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import QLineEdit

script_dir = os.path.dirname(os.path.realpath(__file__))
log_file = os.path.join(script_dir, 'os_boot_selector.log')

logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

GRUB_CFG_PATH = "/boot/grub/grub.cfg"
sudo_password = None


def is_uefi_mode():
    return os.path.exists("/sys/firmware/efi")


def is_efivarfs_mounted():
    try:
        output = subprocess.check_output(['mount']).decode()
        return 'efivarfs on /sys/firmware/efi/efivars' in output
    except Exception as e:
        logging.error(f"Failed to check efivarfs mount: {e}")
        return False


def get_grub_entries():
    entries = []
    try:
        with open(GRUB_CFG_PATH, 'r') as file:
            for line in file:
                match = re.search(r"menuentry '([^']+)'", line)
                if match:
                    entries.append(match.group(1))
        logging.info(f"Successfully fetched {len(entries)} GRUB entries.")
    except Exception as e:
        logging.error(f"Error reading grub.cfg: {e}")
    return entries


def get_uefi_entries():
    entries = []
    try:
        result = subprocess.run(['efibootmgr', '-v'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            match = re.search(r'Boot([0-9A-Fa-f]{4})\*?\s+(.+)', line)
            if match:
                bootnum = match.group(1)
                name = match.group(2).strip()
                entries.append((bootnum, name))
        logging.info(f"Successfully fetched {len(entries)} UEFI entries.")
    except FileNotFoundError:
        logging.error("efibootmgr not found.")
    except Exception as e:
        logging.error(f"Error reading UEFI boot entries: {e}")
    return entries


def get_default_entry():
    try:
        result = subprocess.run(['grub-editenv', 'list'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if line.startswith("saved_entry="):
                logging.info(f"Default GRUB entry found: {line.split('=')[1]}")
                return line.split("=")[1]
    except Exception as e:
        logging.error(f"Could not read default GRUB entry: {e}")
    return None


def run_sudo_command(command_list, password):
    try:
        proc = subprocess.run(
            ['sudo', '-S'] + command_list,
            input=password + '\n',
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
            error_msg = f"Command failed: {' '.join(command_list)}\n{proc.stderr.strip()}"
            logging.error(error_msg)
            return False, error_msg
        logging.info(f"Successfully executed: {' '.join(command_list)}")
        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = f"Sudo command failed: {e.stderr}"
        logging.error(error_msg)
        return False, error_msg


class OSBootSelector(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Boot Manager")
        self.setMinimumSize(500, 300)
        self.entry_map = {}
        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout()
        sidebar_layout = QVBoxLayout()
        control_layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)

        grub_entries = get_grub_entries()
        uefi_entries = get_uefi_entries()
        all_entries = []

        for bootnum, name in uefi_entries:
            display = f"{name} (Boot{bootnum})"
            self.entry_map[display] = bootnum
            all_entries.append(display)

        for i, name in enumerate(grub_entries):
            display = f"{name} (GRUB{i})"
            self.entry_map[display] = str(i)
            all_entries.append(display)

        default_entry = get_default_entry()

        for entry in all_entries:
            key = self.entry_map[entry]
            item = QListWidgetItem(entry)
            if default_entry == key:
                item.setText(item.text() + "  ✅ (default)")
                item.setForeground(QBrush(QColor("green")))
                font = QFont()
                font.setBold(True)
                item.setFont(font)
            self.list_widget.addItem(item)

        sidebar_layout.addWidget(QLabel("Installed Operating Systems:"))
        sidebar_layout.addWidget(self.list_widget)

        reboot_btn = QPushButton("Reboot into Selected OS")
        reboot_btn.clicked.connect(self.reboot_selected)

        default_btn = QPushButton("Set as Default OS")
        default_btn.clicked.connect(self.set_default_os)

        control_layout.addWidget(reboot_btn)
        control_layout.addWidget(default_btn)
        control_layout.addStretch()

        main_layout.addLayout(sidebar_layout, 2)
        main_layout.addLayout(control_layout, 1)
        self.setLayout(main_layout)

    def get_selected_index(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No selection", "Please select an OS.")
            return None
        raw_text = selected_items[0].text().replace("  ✅ (default)", "").strip()
        return self.entry_map.get(raw_text)

    def prompt_for_password(self):
        global sudo_password
        while True:
            if sudo_password:
                return sudo_password
            password, ok = QInputDialog.getText(self, "Sudo Password Required", "Enter your sudo password:", echo=QLineEdit.Password)
            if ok:
                success, _ = run_sudo_command(['echo', 'verified'], password)
                if success:
                    sudo_password = password
                    return password
                else:
                    QMessageBox.critical(self, "Authentication Failed", "Incorrect password. Try again.")
            else:
                return None

    def reboot_selected(self):
        index = self.get_selected_index()
        if not index:
            return

        if not is_uefi_mode():
            QMessageBox.critical(self, "Error", "System is not in UEFI mode.")
            return

        if not is_efivarfs_mounted():
            QMessageBox.critical(self, "Error", "EFI variables are not accessible. Ensure efivarfs is mounted.")
            return

        confirm = QMessageBox.question(
            self, "Confirm Reboot",
            f"Reboot into entry {index}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        password = self.prompt_for_password()
        if not password:
            return

        if index.isdigit():  # GRUB
            success, err = run_sudo_command(['efibootmgr', '-n', index], password)
        else:  # UEFI
            success, err = run_sudo_command(['efibootmgr', '-n', index], password)

        if success:
            success2, err2 = run_sudo_command(['reboot'], password)
            if success2:
                QMessageBox.information(self, "Rebooting", "System is rebooting now...")
            else:
                QMessageBox.critical(self, "Reboot Failed", f"Failed to reboot.\n{err2}")
        else:
            QMessageBox.critical(self, "BootNext Failed", f"Failed to set one-time boot.\n{err}")

    def set_default_os(self):
        index = self.get_selected_index()
        if not index:
            return

        password = self.prompt_for_password()
        if not password:
            return

        if index.isdigit():  # GRUB
            success, err = run_sudo_command(['grub-set-default', index], password)
            if success:
                QMessageBox.information(self, "Success", f"Set GRUB entry #{index} as default.")
            else:
                QMessageBox.critical(self, "Error", f"Failed to set GRUB default.\n{err}")
        else:  # UEFI
            # Get full current boot order
            result = subprocess.run(['efibootmgr'], capture_output=True, text=True)
            current_order = []
            for line in result.stdout.splitlines():
                if line.startswith("BootOrder:"):
                    current_order = line.split(":")[1].strip().split(",")
                    break
            new_order = [index] + [x for x in current_order if x != index]

            success, err = run_sudo_command(['efibootmgr', '--bootorder'] + new_order, password)
            if success:
                QMessageBox.information(self, "Success", f"Set Boot{index} as default UEFI boot option.")
            else:
                QMessageBox.critical(self, "Error", f"Failed to set UEFI boot order.\n{err}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OSBootSelector()
    window.show()
    logging.info("Boot Manager application started.")
    sys.exit(app.exec_())
