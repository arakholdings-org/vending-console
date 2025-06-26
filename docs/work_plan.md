# Vending Machine Console Application Work Plan

## 1. System Architecture Overview

### 1.1 Core Components

- Serial Communication Manager
- Command Handler
- State Manager
- Payment System Interface (future)
- Message Builder
- Main Loop Handler

### 1.2 Communication Flow

```
[Main Loop] -> [Serial Manager] -> [VMC]
     ↑              ↑               |
     |              |               |
     └──────────────┴───────────────┘
```

## 2. Implementation Plan

### Phase 1: Basic Communication Setup

1. Create a command dictionary containing all hex codes

   ```python
   COMMANDS = {
       'POLL': {'code': 0x41, 'description': 'Poll request'},
       'ACK': {'code': 0x42, 'description': 'Acknowledgment'},
       # ... other commands
   }
   ```

2. Implement Serial Communication Class

   - Initialize RS232 connection (57600 baud, 8 data bits, 1 stop bit, no parity)
   - Handle connection/disconnection
   - Basic read/write operations

3. Implement Message Builder

   - Create packet structure (STX + Command + Length + PackNo + Text + XOR)
   - XOR checksum calculator
   - Message validator

4. Create Basic Loop Handler
   - Implement infinite loop with proper termination
   - Handle POLL/ACK basic flow
   - Implement command queue system

### Phase 2: Core Dispensing Implementation

1. Implement Core Dispensing Commands

   - Select to buy (0x03)
   - Direct drive selection (0x06)
   - Handle dispensing status (0x04)

2. Create State Management

   - Track current machine state
   - Monitor dispensing process
   - Handle errors and timeouts

3. Implement Basic Console Interface
   - Display available selections
   - Show machine status
   - Basic command input system

### Phase 3: Inventory Management

1. Implement Selection Management

   - Track selection status
   - Monitor inventory levels
   - Handle product information

2. Create Configuration System
   - Load/save machine configuration
   - Handle tray settings
   - Manage product mappings

### Phase 4: Payment System Integration (Future)

1. Define Payment Interface

   - Create abstract payment handler
   - Define required payment methods
   - Plan integration points

2. Implement Mock Payment System
   - Simulate payment flow
   - Handle basic transactions
   - Prepare for real payment integration

### Phase 5: Testing & Validation

1. Create Test Cases

   - Communication tests
   - Command handling tests
   - State management tests
   - End-to-end flow tests

2. Implement Logging System
   - Track all communications
   - Monitor errors
   - Create debugging tools

## 3. File Structure

```
vending_console/
├── commands/
│   ├── __init__.py
│   ├── command_definitions.py
│   └── command_handler.py
├── communication/
│   ├── __init__.py
│   ├── serial_manager.py
│   └── message_builder.py
├── state/
│   ├── __init__.py
│   └── state_manager.py
├── payment/
│   ├── __init__.py
│   └── payment_interface.py
├── utils/
│   ├── __init__.py
│   ├── checksum.py
│   └── helpers.py
└── main.py
```

## 4. Implementation Priority

1. **High Priority (Phase 1)**

   - Basic serial communication
   - POLL/ACK handling
   - Command dictionary setup
   - Message building/parsing

2. **Medium Priority (Phase 2)**

   - Core dispensing commands
   - Basic console interface
   - State management
   - Error handling

3. **Low Priority (Future)**
   - Payment system integration
   - Advanced error recovery
   - UI improvements
   - Extended logging

## 5. Testing Strategy

1. **Unit Testing**

   - Test message building
   - Test checksum calculation
   - Test command handling
   - Test state transitions

2. **Integration Testing**

   - Test communication flow
   - Test dispensing process
   - Test error scenarios
   - Test full operation cycles

3. **System Testing**
   - End-to-end flow testing
   - Performance testing
   - Error recovery testing
   - Long-running stability tests

## 6. Notes and Considerations

- All commands should be centralized in a single dictionary for easy maintenance
- Implement proper error handling and recovery mechanisms
- Use async programming for the main loop to handle concurrent operations
- Keep the system modular for easy future expansion
- Document all command structures and flows
- Add extensive logging for debugging
- Consider implementing a simulator for testing without hardware
