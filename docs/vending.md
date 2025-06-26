# VMC - Upper Computer Communication Protocol

## 1. Description

This document describes the communication process between the vending machine control board (hereinafter referred as VMC) and upper computer (controller with RS232 communication interface, such as ARM mother board, X86 mother board).

VMC receives commands from upper computer, and controls motor to rotate. VMC processes the data from payment system, then sends the data to upper computer. Upper computer communicates with VMC via RS232 asynchronous communication protocol.

**Communication Parameters:**

- Baud rate: 57600
- Data bits: 8
- Stop bit: 1
- Parity checking: None

## 2. Communication Process

During the whole communication process, VMC works as host, and upper computer works as slave. Ask and answer interchangeably. Each communication starts from VMC, ends by upper computer.

### Process 1 - Poll with ACK

```
VMC -> POLL -> Upper computer
Upper computer -> ACK -> VMC
```

### Process 2 - Poll with Command

```
VMC -> POLL -> Upper computer
Upper computer -> COMMAND -> VMC
VMC -> ACK -> Upper computer
```

### Process 3 - Data Transfer

```
VMC -> Data -> Upper computer
Upper computer -> ACK -> VMC
```

### Communication Rules

- **Poll Frequency:** Every 200ms, VMC will query upper computer
- **Response Time:** Upper computer must send command within 100ms after receiving POLL
- **Retry Logic:** Both sides can resend packets up to 5 times
- **Communication Number:** Ranges from 1-255, increments after successful completion

## 3. Data Definition

### Packet Structure

| Field       | Size    | Description                         |
| ----------- | ------- | ----------------------------------- |
| STX         | 2 bytes | Start of packet (0xfa 0xfb)         |
| Command     | 1 byte  | Command type                        |
| Length      | 1 byte  | PackNO+Text length                  |
| PackNO+Text | n bytes | Communication number + Command Text |
| XOR         | 1 byte  | XOR check from STX to TEXT          |

### Standard Packets

**POLL Packet:**

```
0xfa 0xfb 0x41 0x00 0x40
```

**ACK Packet:**

```
0xfa 0xfb 0x42 0x00 0x43
```

## 4. Data and Command Description

### Core Dispensing Commands

You can use the following 3 commands to make the machine dispense products:

- **4.3.2** Upper computer selects to buy
- **4.3.5** Upper computer drives selection directly
- **4.3.3** VMC dispensing status

> **Note:** Using only these commands means inventory and price are managed by upper computer APP, not VMC.

## 4.1 Payment System Information Interaction

### 4.1.1 VMC Collects Money Notice (VMC sends out)

| Field       | Value | Size    | Description                                                               |
| ----------- | ----- | ------- | ------------------------------------------------------------------------- |
| Command     | 0x21  | 1 byte  | Money collection notice                                                   |
| Length      | 6     | 1 byte  | Packet length                                                             |
| PackNO+Text | -     | 6 bytes | Communication Number (1) + Mode (1) + Amount (4) + Card Number (optional) |

**Payment Modes:**

| Mode | Description      |
| ---- | ---------------- |
| 1    | Bill             |
| 2    | Coin             |
| 3    | IC card          |
| 4    | Bank card        |
| 5    | Wechat payment   |
| 6    | Alipay           |
| 7    | Jingdong Pay     |
| 8    | Swallowing money |
| 9    | Union scan pay   |

### 4.1.2 VMC Reports Current Amount (VMC sends out)

| Field       | Value | Size    | Description                                   |
| ----------- | ----- | ------- | --------------------------------------------- |
| Command     | 0x23  | 1 byte  | Current amount report                         |
| Length      | 5     | 1 byte  | Packet length                                 |
| PackNO+Text | -     | 5 bytes | Communication number (1) + current amount (4) |

### 4.1.3 POS Display Requests (VMC sends out)

| Field       | Value | Size     | Description                                                      |
| ----------- | ----- | -------- | ---------------------------------------------------------------- |
| Command     | 0x24  | 1 byte   | Display request                                                  |
| Length      | 19    | 1 byte   | Packet length                                                    |
| PackNO+Text | -     | 19 bytes | Communication number (1) + Text (16) + 0x00 (1) + row number (1) |

### 4.1.4 Upper Computer Requests to Give Change (Upper computer sends out)

**Request:**

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x25  | 1 byte | Change request       |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

**Response:**

| Field       | Value | Size    | Description                                                  |
| ----------- | ----- | ------- | ------------------------------------------------------------ |
| Command     | 0x26  | 1 byte  | Change response                                              |
| Length      | 9     | 1 byte  | Packet length                                                |
| PackNO+Text | -     | 9 bytes | Communication number (1) + bill change (4) + coin change (4) |

### 4.1.5 Upper Computer Receives Money (Upper computer sends out)

| Field       | Value | Size    | Description                                                               |
| ----------- | ----- | ------- | ------------------------------------------------------------------------- |
| Command     | 0x27  | 1 byte  | Money received                                                            |
| Length      | 6     | 1 byte  | Packet length                                                             |
| PackNO+Text | -     | 6 bytes | Communication number (1) + Mode (1) + Amount (4) + Card number (optional) |

### 4.1.6 Upper Computer Sets Coin/Note Acceptance (Upper computer sends out)

| Field       | Value | Size    | Description                                     |
| ----------- | ----- | ------- | ----------------------------------------------- |
| Command     | 0x28  | 1 byte  | Acceptance setting                              |
| Length      | 6     | 1 byte  | Packet length                                   |
| PackNO+Text | -     | 6 bytes | Communication number (1) + Mode (1) + value (2) |

**Mode Values:**

- 0: Notes
- 1: Coin

**Value:** 16-bit field where each bit represents a value channel (0xffff = accept all, 0x0000 = prohibit all)

## 4.2 Tray Configuration Information Interaction

### 4.2.1 VMC Reports Selection Info (VMC sends out)

| Field       | Value | Size     | Description                                                                                                     |
| ----------- | ----- | -------- | --------------------------------------------------------------------------------------------------------------- |
| Command     | 0x11  | 1 byte   | Selection info                                                                                                  |
| Length      | 12    | 1 byte   | Packet length                                                                                                   |
| PackNO+Text | -     | 12 bytes | Comm number (1) + selection number (2) + price (4) + inventory (1) + capacity (1) + product ID (2) + status (1) |

**Selection Status:**

- 0: Normal
- 1: Selection pause

### 4.2.2 Set Selection Price (Both VMC and Upper computer)

| Field       | Value | Size    | Description                                                 |
| ----------- | ----- | ------- | ----------------------------------------------------------- |
| Command     | 0x12  | 1 byte  | Set price                                                   |
| Length      | 7     | 1 byte  | Packet length                                               |
| PackNO+Text | -     | 7 bytes | Communication number (1) + selection number (2) + price (4) |

**Special Selection Numbers:**

- 1000: All selections on tray 0
- 1001: All selections on tray 1
- 1009: All selections on tray 9
- 0000: All selections on machine

### 4.2.3 Set Selection Inventory (Both VMC and Upper computer)

| Field       | Value | Size    | Description                                                     |
| ----------- | ----- | ------- | --------------------------------------------------------------- |
| Command     | 0x13  | 1 byte  | Set inventory                                                   |
| Length      | 4     | 1 byte  | Packet length                                                   |
| PackNO+Text | -     | 4 bytes | Communication number (1) + selection number (2) + inventory (1) |

### 4.2.4 Set Selection Capacity (Both VMC and Upper computer)

| Field       | Value | Size    | Description                                                    |
| ----------- | ----- | ------- | -------------------------------------------------------------- |
| Command     | 0x14  | 1 byte  | Set capacity                                                   |
| Length      | 4     | 1 byte  | Packet length                                                  |
| PackNO+Text | -     | 4 bytes | Communication number (1) + selection number (2) + capacity (1) |

### 4.2.5 Set Selection Product ID (Both VMC and Upper computer)

| Field       | Value | Size    | Description                                                          |
| ----------- | ----- | ------- | -------------------------------------------------------------------- |
| Command     | 0x15  | 1 byte  | Set product ID                                                       |
| Length      | 5     | 1 byte  | Packet length                                                        |
| PackNO+Text | -     | 5 bytes | Communication number (1) + selection number (2) + product number (2) |

### 4.2.6 Press Fully Loading Button (VMC sends out)

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x17  | 1 byte | Fully loading        |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

## 4.3 Dispensing Information Interaction

### 4.3.1 Check Selection Status (Upper computer sends out)

**Request:**

| Field       | Value | Size    | Description                                     |
| ----------- | ----- | ------- | ----------------------------------------------- |
| Command     | 0x01  | 1 byte  | Check selection                                 |
| Length      | 4     | 1 byte  | Packet length                                   |
| PackNO+Text | -     | 4 bytes | Communication number (1) + selection number (2) |

**Response:**

| Field       | Value | Size    | Description                                                  |
| ----------- | ----- | ------- | ------------------------------------------------------------ |
| Command     | 0x02  | 1 byte  | Selection status                                             |
| Length      | 4     | 1 byte  | Packet length                                                |
| PackNO+Text | -     | 4 bytes | Communication number (1) + status (1) + selection number (2) |

**Status Codes:**

| Code | Description                                    |
| ---- | ---------------------------------------------- |
| 0x01 | Normal                                         |
| 0x02 | Out of stock                                   |
| 0x03 | Selection doesn't exist                        |
| 0x04 | Selection pause                                |
| 0x05 | Product inside elevator                        |
| 0x06 | Delivery door unlocked                         |
| 0x07 | Elevator error                                 |
| 0x08 | Elevator self-checking faulty                  |
| 0x09 | Microwave oven delivery door closing error     |
| 0x10 | Microwave oven inlet door opening error        |
| 0x11 | Microwave oven inlet door closing error        |
| 0x12 | Didn't detect box lunch                        |
| 0x13 | Box lunch is heating                           |
| 0x14 | Microwave oven delivery door opening error     |
| 0x15 | Please take out the lunch box in the microwave |
| 0x16 | Staypole return error                          |
| 0x17 | Main motor fault                               |
| 0x18 | Translation motor fault                        |
| 0x19 | Staypole push error                            |
| 0x20 | Elevator entering microwave oven error         |
| 0x21 | Elevator exiting microwave oven error          |
| 0x22 | Pushrod pushing error in microwave oven        |
| 0x23 | Pushrod returning error in microwave oven      |

### 4.3.2 Upper Computer Selects to Buy (Upper computer sends out)

| Field       | Value | Size    | Description                                     |
| ----------- | ----- | ------- | ----------------------------------------------- |
| Command     | 0x03  | 1 byte  | Select to buy                                   |
| Length      | 3     | 1 byte  | Packet length                                   |
| PackNO+Text | -     | 3 bytes | Communication number (1) + selection number (2) |

### 4.3.3 VMC Dispensing Status (VMC sends out)

| Field       | Value  | Size     | Description                                                                                   |
| ----------- | ------ | -------- | --------------------------------------------------------------------------------------------- |
| Command     | 0x04   | 1 byte   | Dispensing status                                                                             |
| Length      | 5 or 3 | 1 byte   | Packet length                                                                                 |
| PackNO+Text | -      | Variable | Communication number (1) + Status (1) + Selection number (2) + Microwave number (1, optional) |

**Dispensing Status Codes:**

| Code | Description                                         |
| ---- | --------------------------------------------------- |
| 0x01 | Dispensing                                          |
| 0x02 | Dispensing successfully                             |
| 0x03 | Selection jammed                                    |
| 0x04 | Motor doesn't stop normally                         |
| 0x06 | Motor doesn't exist                                 |
| 0x07 | Elevator error                                      |
| 0x10 | Elevator is ascending                               |
| 0x11 | Elevator is descending                              |
| 0x12 | Elevator ascending error                            |
| 0x13 | Elevator descending error                           |
| 0x14 | Microwave delivery door is closing                  |
| 0x15 | Microwave delivery door closing error               |
| 0x16 | Microwave inlet door is opening                     |
| 0x17 | Microwave inlet door opening error                  |
| 0x18 | Pushing lunch box into microwave                    |
| 0x19 | Microwave inlet door is closing                     |
| 0x20 | Microwave inlet door closing error                  |
| 0x21 | Don't detect lunch box in microwave                 |
| 0x22 | Lunch box is heating                                |
| 0x23 | Lunch box heating remaining time, second            |
| 0x24 | Please take out the lunch box (successful purchase) |
| 0x25 | Staypole return error                               |
| 0x26 | Microwave delivery door is opening                  |
| 0x28 | Staypole push error                                 |
| 0x29 | Elevator entering microwave oven error              |
| 0x30 | Elevator exiting microwave oven error               |
| 0x31 | Pushrod pushing error in microwave oven             |
| 0x32 | Pushrod retiring error in microwave oven            |
| 0xff | Purchase terminated                                 |

### 4.3.4 VMC Selects/Cancels Selection (Both VMC and Upper computer)

| Field       | Value | Size    | Description                                     |
| ----------- | ----- | ------- | ----------------------------------------------- |
| Command     | 0x05  | 1 byte  | Select/cancel                                   |
| Length      | 3     | 1 byte  | Packet length                                   |
| PackNO+Text | -     | 3 bytes | Communication number (1) + selection number (2) |

**Note:** Selection number 0x0000 means cancel selection.

### 4.3.5 Upper Computer Drives Selection Directly (Upper computer sends out)

| Field       | Value | Size    | Description                                                                                    |
| ----------- | ----- | ------- | ---------------------------------------------------------------------------------------------- |
| Command     | 0x06  | 1 byte  | Direct drive                                                                                   |
| Length      | 5     | 1 byte  | Packet length                                                                                  |
| PackNO+Text | -     | 5 bytes | Communication number (1) + Enable drop sensor (1) + Enable elevator (1) + selection number (2) |

**Enable Fields:**

- 0: No
- 1: Enable

### 4.3.6 Upper Computer Requests Machine Status (Upper computer sends out)

**Request:**

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x53  | 1 byte | Status request       |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

**Response:**

| Field       | Value | Size     | Description                       |
| ----------- | ----- | -------- | --------------------------------- |
| Command     | 0x54  | 1 byte   | Status response                   |
| Length      | 1     | 1 byte   | Packet length                     |
| PackNO+Text | -     | Variable | Communication number (1) + status |

**Machine Status Codes:**

| Code | Description                  |
| ---- | ---------------------------- |
| 0x00 | Normal                       |
| 0x01 | Product in elevator          |
| 0x02 | Delivery door not closed     |
| 0x03 | Elevator error               |
| 0x04 | Elevator self-checking error |

## 4.4 Other Commands

### 4.4.1 Upper Computer Checks IC Card Balance (Upper computer sends out)

**Request:**

| Field       | Value | Size    | Description                            |
| ----------- | ----- | ------- | -------------------------------------- |
| Command     | 0x61  | 1 byte  | Check balance                          |
| Length      | 1     | 1 byte  | Packet length                          |
| PackNO+Text | -     | 2 bytes | Communication number (1) + Command (1) |

**Commands:**

- 1: Check balance
- 2: Cancel to check balance

**Response:**

| Field       | Value | Size    | Description                                         |
| ----------- | ----- | ------- | --------------------------------------------------- |
| Command     | 0x62  | 1 byte  | Balance response                                    |
| Length      | 6     | 1 byte  | Packet length                                       |
| PackNO+Text | -     | 6 bytes | Communication number (1) + Status (1) + Balance (4) |

**Status:**

- 1: Normal
- 2: Card error

### 4.4.2 Lower Computer Calls Android Menu (VMC sends out)

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x63  | 1 byte | Call menu            |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

### 4.4.3 Upper Computer Sets VMC Query Interval (Upper computer sends out)

| Field       | Value | Size    | Description                             |
| ----------- | ----- | ------- | --------------------------------------- |
| Command     | 0x16  | 1 byte  | Set interval                            |
| Length      | 2     | 1 byte  | Packet length                           |
| PackNO+Text | -     | 2 bytes | Communication number (1) + Interval (1) |

**Interval Values:**

- 1: 100ms
- 2: 200ms
- 5: 500ms
- Maximum: 2s

### 4.4.4 Information Synchronization Command (Both VMC and Upper computer)

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x31  | 1 byte | Synchronization      |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

**Synchronization Process:**

```
VMC -> Request info synchronization -> Upper computer
Upper computer -> ACK -> VMC
VMC -> POLL -> Upper computer
Upper computer -> Request info synchronization -> VMC
```

### 4.4.5 Upper Computer Requests Machine Status (Upper computer sends out)

**Request:**

| Field       | Value | Size   | Description          |
| ----------- | ----- | ------ | -------------------- |
| Command     | 0x51  | 1 byte | Machine status       |
| Length      | 1     | 1 byte | Packet length        |
| PackNO+Text | -     | 1 byte | Communication number |

**Response:**

| Field       | Value    | Size     | Description                                                                                                                                                                                                                                  |
| ----------- | -------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Command     | 0x52     | 1 byte   | Machine status response                                                                                                                                                                                                                      |
| Length      | Variable | 1 byte   | Packet length                                                                                                                                                                                                                                |
| PackNO+Text | -        | Variable | Communication number + Bill acceptor status + Coin acceptor status + Card reader status + Temperature controller status + Door status + Bill change (4) + Coin change (4) + Machine ID (10) + Machine temperature (8) + Machine humidity (8) |

### 4.4.6 Upper Computer Requests VMC Card Deduction

| Field       | Value | Size    | Description                                     |
| ----------- | ----- | ------- | ----------------------------------------------- |
| Command     | 0x64  | 1 byte  | Card deduction                                  |
| Length      | 5     | 1 byte  | Packet length                                   |
| PackNO+Text | -     | 5 bytes | Communication number (1) + Deduction amount (4) |

**Note:** Deduction amount = 0 means cancel deduction.

### 4.4.7 VMC Sends Microwave Info

| Field       | Value    | Size     | Description                                                        |
| ----------- | -------- | -------- | ------------------------------------------------------------------ |
| Command     | 0x66     | 1 byte   | Microwave info                                                     |
| Length      | Variable | 1 byte   | Packet length                                                      |
| PackNO+Text | -        | Variable | Communication number (1) + Microwave amount (1) + Microwave status |

**Microwave Status:**

- 0: Available
- 1: Unavailable

## 4.5 Menu Commands (Replace keypad and 5 inches display)

### Base Command Structure

| Field       | Value    | Size     | Description                                      |
| ----------- | -------- | -------- | ------------------------------------------------ |
| Command     | 0x70     | 1 byte   | Menu command                                     |
| Length      | Variable | 1 byte   | Packet length                                    |
| PackNO+Text | -        | Variable | Communication number + Command type + Parameters |

### Response Structure

| Field       | Value    | Size     | Description                                                 |
| ----------- | -------- | -------- | ----------------------------------------------------------- |
| Command     | 0x71     | 1 byte   | Menu response                                               |
| Length      | Variable | 1 byte   | Packet length                                               |
| PackNO+Text | -        | Variable | Communication number + Command type + Operation type + Data |

### 4.5.1 Coin System Setting (Command type: 0x01)

**Parameters:**

| Operation               | Description                            |
| ----------------------- | -------------------------------------- |
| 0x00                    | Read current coin system configuration |
| 0x01 + Coin System Type | Set coin system type                   |

**Coin System Types:**

- 0x01: Coin acceptor
- 0x02: HOPPER

### 4.5.2 Selection Mode Setting (Command type: 0x02)

**Parameters:**

| Operation                            | Description                                  |
| ------------------------------------ | -------------------------------------------- |
| 0x00 + layer number                  | Read selection mode of specific layer (0-99) |
| 0x01 + layer number + Selection mode | Set selection mode of specific layer         |

**Selection Modes:**

- 0x01: Spiral
- 0x02: Belt
- 0x03: Hook

### 4.5.3 Motor AD Setting (Command type: 0x03)

**Parameters:**

| Operation                        | Description                       |
| -------------------------------- | --------------------------------- |
| 0x00 + Machine number            | Read motor AD of specific machine |
| 0x01 + Machine number + Motor AD | Set motor AD of specific machine  |

**Machine Numbers:**

- 0: Master machine
- 1-9: Slave machines 1-9

**Motor AD Range:** 20-250

### 4.5.4 Selection Coupling Setting (Command type: 0x04)

**Parameters:**

| Operation                                 | Description                                         |
| ----------------------------------------- | --------------------------------------------------- |
| 0x00 + Selection number                   | Read coupling status of specific selection (1-1000) |
| 0x01 + Selection number + Coupling status | Set coupling status of specific selection           |

**Coupling Status:**

- 0x01: No coupling
- 0x02: 2 selections coupling
- 0x03: 3 selections coupling

### 4.5.5 Clear Selection Coupling (Command type: 0x05)

**Parameters:**

| Operation | Description              |
| --------- | ------------------------ |
| 0x01      | Clear selection coupling |

### 4.5.6 Coupling Synchronizing Time (Command type: 0x06)

**Parameters:**

| Operation                              | Description                      |
| -------------------------------------- | -------------------------------- |
| 0x00 + Machine number                  | Read coupling synchronizing time |
| 0x01 + Machine number + Time (2 bytes) | Set coupling synchronizing time  |

**Time Range:** 1200-2200ms

### 4.5.7 MotorShort Value Setting (Command type: 0x07)

**Parameters:**

| Operation                               | Description           |
| --------------------------------------- | --------------------- |
| 0x00 + Machine number                   | Read motorshort value |
| 0x01 + Machine number + Value (2 bytes) | Set motorshort value  |

**Value Range:** 700-900

### 4.5.8 Machine ID Setting (Command type: 0x08)

**Parameters:**

| Operation                     | Description     |
| ----------------------------- | --------------- |
| 0x00                          | Read machine ID |
| 0x01 + Machine ID (10 digits) | Set machine ID  |

### 4.5.9 System Time Setting (Command type: 0x09)

**Parameters:**

| Operation             | Description       |
| --------------------- | ----------------- |
| 0x00                  | Read machine time |
| 0x01 + Time (7 bytes) | Set machine time  |

**Time Format:** YYYYMMDDHHMMSS (e.g., 20171130095003)

### 4.5.10 Decimal Point Digit Setting (Command type: 0x10)

**Parameters:**

| Operation    | Description                          |
| ------------ | ------------------------------------ |
| 0x00         | Read decimal point digit             |
| 0x01 + Digit | Set decimal point digit (0, 1, or 2) |

### 4.5.11 Query Selection Configuration (Command type: 0x42)

**Parameters:**

| Operation                         | Description                   |
| --------------------------------- | ----------------------------- |
| 0x00 + Selection number (2 bytes) | Query selection configuration |

**Response:**

| Field       | Value    | Size     | Description                                                                                                                                                                                                                                                              |
| ----------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Command     | 0x71     | 1 byte   | Menu response                                                                                                                                                                                                                                                            |
| Length      | Variable | 1 byte   | Packet length                                                                                                                                                                                                                                                            |
| PackNO+Text | -        | Variable | Communication number + Command type (0x42) + Operation type (0x00) + Selection price (4 bytes) + Inventory (2 bytes) + Capacity (1 byte) + Product ID (2 bytes) + Selection Mode (1 byte) + Drop sensor status (1 byte) + Jammed set (1 byte) + Turn 1/4 circle (1 byte) |

**Selection Mode Values:**

- 0x01: Coil
- 0x02: Belt
- 0x03: Hook

**Drop Sensor Status:**

- 0x00: Enable
- 0x01: Close

**Jammed Set:**

- 0x00: Can't buy
- 0x01: Continue service

**Turn 1/4 Circle:**

- 0x00: Close
- 0x01: Enable

### Additional Menu Commands (4.5.12 - 4.5.49)

The document continues with many more menu commands following the same pattern, including settings for:

- Delivery door close time
- Connecting lift settings
- Anti-theft board settings
- Coin counts (50c, 1 dollar)
- Light control
- Unionpay/POS settings
- Bill acceptance settings
- Temperature controller
- Drop sensor settings
- Sales information queries
- Error management

Each command follows the same request/response pattern with command type 0x70/0x71 and specific parameters for different operations.

---

**Note:** This document provides the complete communication protocol for VMC-Upper Computer interaction. All commands use the same basic packet structure with STX, Command, Length, Data, and XOR fields.
