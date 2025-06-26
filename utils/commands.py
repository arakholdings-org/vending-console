VMC_COMMANDS = {
    "POLL": {
        "code": 0x41,
        "description": "Poll packet from VMC",
    },
    "ACK": {
        "code": 0x42,
        "description": "Acknowledgment packet",
    },
    # Payment System Commands
    "MONEY_NOTICE": {
        "code": 0x21,
        "description": "VMC money collection notice",
    },
    "CURRENT_AMOUNT": {
        "code": 0x23,
        "description": "VMC reports current amount",
    },
    "DISPLAY_REQUEST": {
        "code": 0x24,
        "description": "POS display requests",
    },
    "CHANGE_REQUEST": {
        "code": 0x25,
        "description": "Request to give change",
    },
    "CHANGE_RESPONSE": {
        "code": 0x26,
        "description": "Change response",
    },
    "MONEY_RECEIVED": {
        "code": 0x27,
        "description": "Upper computer receives money",
    },
    "SET_ACCEPTANCE": {
        "code": 0x28,
        "description": "Set coin/note acceptance",
    },
    # Tray Configuration Commands
    "SELECTION_INFO": {
        "code": 0x11,
        "description": "VMC reports selection info",
    },
    "SET_PRICE": {
        "code": 0x12,
        "description": "Set selection price",
    },
    "SET_INVENTORY": {
        "code": 0x13,
        "description": "Set selection inventory",
    },
    "SET_CAPACITY": {
        "code": 0x14,
        "description": "Set selection capacity",
    },
    "SET_PRODUCT_ID": {
        "code": 0x15,
        "description": "Set selection product ID",
    },
    "FULLY_LOADING": {
        "code": 0x17,
        "description": "Press fully loading button",
    },
    # Dispensing Commands
    "CHECK_SELECTION": {
        "code": 0x01,
        "description": "Check selection status",
    },
    "SELECTION_STATUS": {
        "code": 0x02,
        "description": "Selection status response",
    },
    "SELECT_TO_BUY": {
        "code": 0x03,
        "description": "Upper computer selects to buy",
    },
    "DISPENSING_STATUS": {
        "code": 0x04,
        "description": "VMC dispensing status",
    },
    "SELECT_CANCEL": {
        "code": 0x05,
        "description": "Select/cancel selection",
    },
    "DIRECT_DRIVE": {
        "code": 0x06,
        "description": "Direct drive selection",
    },
    "MACHINE_STATUS_REQ": {
        "code": 0x53,
        "description": "Request machine status",
    },
    "MACHINE_STATUS_RESP": {
        "code": 0x54,
        "description": "Machine status response",
    },
    # Other Commands
    "CHECK_IC_BALANCE": {
        "code": 0x61,
        "description": "Check IC card balance",
    },
    "IC_BALANCE_RESP": {
        "code": 0x62,
        "description": "IC balance response",
    },
    "CALL_MENU": {
        "code": 0x63,
        "description": "Call Android menu",
    },
    "SET_QUERY_INTERVAL": {
        "code": 0x16,
        "description": "Set VMC query interval",
    },
    "SYNC_INFO": {
        "code": 0x31,
        "description": "Information synchronization",
    },
    "MACHINE_STATUS": {
        "code": 0x51,
        "description": "Request machine status",
    },
    "MACHINE_STATUS_DETAIL": {
        "code": 0x52,
        "description": "Machine status detail response",
    },
    "CARD_DEDUCTION": {
        "code": 0x64,
        "description": "VMC card deduction",
    },
    "MICROWAVE_INFO": {
        "code": 0x66,
        "description": "VMC sends microwave info",
    },
    # Menu Commands
    "MENU_COMMAND": {
        "code": 0x70,
        "description": "Menu command",
    },
    "MENU_RESPONSE": {
        "code": 0x71,
        "description": "Menu response",
    },
}

# Menu command types
MENU_COMMAND_TYPES = {
    "COIN_SYSTEM": 0x01,
    "SELECTION_MODE": 0x02,
    "MOTOR_AD": 0x03,
    "SELECTION_COUPLING": 0x04,
    "CLEAR_COUPLING": 0x05,
    "COUPLING_SYNC_TIME": 0x06,
    "MOTOR_SHORT": 0x07,
    "MACHINE_ID": 0x08,
    "SYSTEM_TIME": 0x09,
    "DECIMAL_POINT": 0x10,
    "QUERY_SELECTION_CONFIG": 0x42,
}
