import asyncio
import qasync
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QComboBox, QPushButton, QTextEdit, QGroupBox, QFormLayout
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from sms_manager import SMSManager, ProviderType, SMSOrder, RentStatus, SMSException

class SMSWidget(QWidget):
    """
    Re-usable SMS Management Widget for PyQt6
    """
    code_received = pyqtSignal(str) # Emits the code when received
    log_message = pyqtSignal(str)   # Emits logs to parent if needed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = None
        self.current_order = None
        self.is_monitoring = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Settings Group ---
        settings_group = QGroupBox("SMS Platform Settings")
        form_layout = QFormLayout()

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["sms-man", "5sim", "vak-sms"])
        
        self.input_api_key = QLineEdit()
        self.input_api_key.setPlaceholderText("Enter API Key")
        self.input_api_key.setEchoMode(QLineEdit.EchoMode.Password)

        self.btn_check_balance = QPushButton("Check Balance")
        self.btn_check_balance.clicked.connect(self.on_check_balance)
        self.lbl_balance = QLabel("Balance: N/A")

        form_layout.addRow("Provider:", self.combo_provider)
        form_layout.addRow("API Key:", self.input_api_key)
        form_layout.addRow(self.btn_check_balance, self.lbl_balance)
        settings_group.setLayout(form_layout)
        layout.addWidget(settings_group)

        # --- Rent Group ---
        rent_group = QGroupBox("Rent Number")
        rent_layout = QFormLayout()

        self.input_country = QLineEdit("us")
        self.input_service = QLineEdit("go") # default google
        self.input_service.setPlaceholderText("e.g. go, tg, wa")
        
        self.btn_rent = QPushButton("Rent Number")
        self.btn_rent.clicked.connect(self.on_rent_number)
        self.btn_rent.setStyleSheet("background-color: #4CAF50; color: white;")

        self.btn_cancel = QPushButton("Cancel/Finish")
        self.btn_cancel.clicked.connect(self.on_cancel_rent)
        self.btn_cancel.setEnabled(False)

        rent_layout.addRow("Country:", self.input_country)
        rent_layout.addRow("Service:", self.input_service)
        rent_layout.addRow(self.btn_rent, self.btn_cancel)
        rent_group.setLayout(rent_layout)
        layout.addWidget(rent_group)

        # --- Status Group ---
        status_group = QGroupBox("Status & Result")
        status_layout = QVBoxLayout()
        
        self.info_layout = QHBoxLayout()
        self.lbl_phone = QLabel("Phone: -")
        self.lbl_phone.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.lbl_phone.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_layout.addWidget(self.lbl_phone)
        status_layout.addLayout(self.info_layout)

        self.lbl_code = QLabel("Code: Waiting...")
        self.lbl_code.setStyleSheet("color: blue; font-size: 16px; font-weight: bold;")
        self.lbl_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addWidget(self.lbl_code)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(100)
        status_layout.addWidget(self.log_area)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Timer for polling
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_sms_status)

    def log(self, msg):
        self.log_area.append(msg)
        self.log_message.emit(msg)

    @qasync.asyncSlot()
    async def on_check_balance(self):
        try:
            self.init_manager()
            balance = await self.manager.get_balance()
            self.lbl_balance.setText(f"Balance: {balance}")
            self.log(f"Balance checked: {balance}")
        except Exception as e:
            self.lbl_balance.setText("Balance: Error")
            self.log(f"Error checking balance: {e}")

    @qasync.asyncSlot()
    async def on_rent_number(self):
        try:
            self.init_manager()
            country = self.input_country.text().strip()
            service = self.input_service.text().strip()
            
            self.log(f"Requesting number for {service} in {country}...")
            self.btn_rent.setEnabled(False)
            
            self.current_order = await self.manager.rent_number(country, service)
            
            self.lbl_phone.setText(f"Phone: {self.current_order.phone_number}")
            self.lbl_code.setText("Code: Waiting...")
            self.log(f"Number rented: {self.current_order.phone_number} (ID: {self.current_order.order_id})")
            
            self.btn_cancel.setEnabled(True)
            self.is_monitoring = True
            self.timer.start(5000) # Poll every 5 seconds

        except Exception as e:
            self.log(f"Rent failed: {e}")
            self.btn_rent.setEnabled(True)

    @qasync.asyncSlot()
    async def check_sms_status(self):
        if not self.current_order or not self.is_monitoring:
            self.timer.stop()
            return

        try:
            # Check for SMS
            self.current_order = await self.manager.check_sms(self.current_order)
            
            if self.current_order.status == RentStatus.RECEIVED or self.current_order.sms_code:
                code = self.current_order.sms_code
                self.lbl_code.setText(f"Code: {code}")
                self.log(f"SMS Received! Code: {code}")
                self.log(f"Full Text: {self.current_order.sms_text}")
                
                self.code_received.emit(code)
                self.is_monitoring = False
                self.timer.stop()
                self.btn_rent.setEnabled(True)
                
            elif self.current_order.status == RentStatus.TIMEOUT:
                self.log("Timeout waiting for SMS.")
                self.is_monitoring = False
                self.timer.stop()
                self.btn_rent.setEnabled(True)
                
        except Exception as e:
            self.log(f"Error checking SMS: {e}")

    @qasync.asyncSlot()
    async def on_cancel_rent(self):
        if self.current_order:
            try:
                self.log("Cancelling order...")
                await self.manager.cancel_rent(self.current_order.order_id)
                self.log("Order cancelled.")
            except Exception as e:
                self.log(f"Cancel failed: {e}")
        
        self.is_monitoring = False
        self.timer.stop()
        self.btn_rent.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_phone.setText("Phone: -")
        self.lbl_code.setText("Code: -")
        self.current_order = None

    def init_manager(self):
        provider_str = self.combo_provider.currentText()
        api_key = self.input_api_key.text().strip()
        
        if not api_key:
            raise ValueError("Please enter API Key")
            
        mapping = {
            "sms-man": ProviderType.SMS_MAN,
            "5sim": ProviderType.FIVE_SIM,
            "vak-sms": ProviderType.VAK_SMS
        }
        
        self.manager = SMSManager(mapping[provider_str], api_key)

# --- Standalone Test Runner ---
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    win = QWidget()
    win.setWindowTitle("SMS Widget Test")
    layout = QVBoxLayout(win)
    sms_widget = SMSWidget()
    layout.addWidget(sms_widget)
    
    win.show()
    
    with loop:
        loop.run_forever()
