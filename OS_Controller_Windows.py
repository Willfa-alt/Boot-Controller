import os
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
log_file = os.path.join(script_dir, 'windows_boot_selector.log')

logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BCDEDIT_CMD = "bcdedit"

sudo_password = None


def is_uefi_mode():
    # On Windows, UEFI mode can be checked using the existence of certain directories
    # such as the Windows EFI system partition.
    return os.path.exists("C:\\Windows\\Boot\\EFI")


def get_bcd_entries():
    # Fetch all boot entries from BCDEdit
    entries = []
    try:
        result = subprocess.run([BCDEDIT_CMD], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "description" in line.lower():
                # Extract the description (boot entry name)
                match = line.strip().split(":")
                if len(match) > 1:
                    name = match[1].strip()
                    entries.append(name)
        logging.info(f"Successfully fetched {len(entries)} boot entries.")
    except Exception as e:
        logging.error(f"Error reading BCDEDIT entries: {e}")
    return entries


def get_default_entry():
    # Retrieve the default boot entry
    try:
        result = subprocess.run([BCDEDIT_CMD], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "default" in line.lower():
                # Extract the GUID of the default entry
                match = line.strip().split(":")
                if len(match) > 1:
                    return match[1].strip()
    except Exception as e:
        logging.error(f"Could not read default boot entry: {e}")
    return None


def run_sudo_command(command_list, password):
    try:
        proc = subprocess.run(
            ['runas', '/user:Administrator'] + command_list,
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

        boot_entries = get_bcd_entries()
        all_entries = []

        for i, name in enumerate(boot_entries):
            display = f"{name} (Boot{i})"
            self.entry_map[display] = name
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
            password, ok = QInputDialog.getText(self, "Administrator Password Required", "Enter your password:", echo=QLineEdit.Password)
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

        success, err = run_sudo_command(['shutdown', '/r', '/t', '0'], password)

        if success:
            QMessageBox.information(self, "Rebooting", "System is rebooting now...")
        else:
            QMessageBox.critical(self, "Reboot Failed", f"Failed to reboot.\n{err}")

    def set_default_os(self):
        index = self.get_selected_index()
        if not index:
            return

        password = self.prompt_for_password()
        if not password:
            return

        success, err = run_sudo_command([BCDEDIT_CMD, '/default', index], password)
        if success:
            QMessageBox.information(self, "Success", f"Set {index} as default boot entry.")
        else:
            QMessageBox.critical(self, "Error", f"Failed to set default boot entry.\n{err}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OSBootSelector()
    window.show()
    logging.info("Boot Manager application started.")
    sys.exit(app.exec_())
