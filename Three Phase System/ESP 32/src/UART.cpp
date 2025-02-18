#include "UART.h"

static UART *instance = NULL;

UART::UART(){
    instance = this;
}

std::tuple<float,float,float,float,float,float,float,float,float> UART::results(){
    // CONSOLE_SERIAL.print("Voltage (1): ");
    // CONSOLE_SERIAL.print(pzem1.voltage());
    // CONSOLE_SERIAL.println("V");
    // CONSOLE_SERIAL.print("Current (1): ");
    // CONSOLE_SERIAL.print(pzem1.current());
    // CONSOLE_SERIAL.println("A");
    // CONSOLE_SERIAL.print("Power (1): ");
    // CONSOLE_SERIAL.print(pzem1.power());
    // CONSOLE_SERIAL.println("W");
    // CONSOLE_SERIAL.print("Voltage (1): ");
    // CONSOLE_SERIAL.print(pzem2.voltage());
    // CONSOLE_SERIAL.println("V");
    // CONSOLE_SERIAL.print("Current (2): ");
    // CONSOLE_SERIAL.print(pzem2.current());
    // CONSOLE_SERIAL.println("A");
    // CONSOLE_SERIAL.print("Power (2): ");
    // CONSOLE_SERIAL.print(pzem2.power());
    // CONSOLE_SERIAL.println("W");
  return std::make_tuple(pzem1.voltage(), pzem1.current(),pzem1.power(),
                          pzem2.voltage(),pzem2.current(),pzem2.power(),
                          pzem3.voltage(),pzem3.current(),pzem3.power()

  );

}


// float UART::voltage(){
//   float voltage = pzem.voltage();
//   if (voltage != NAN) {
//     // CONSOLE_SERIAL.print("Voltage: ");
//     // CONSOLE_SERIAL.print(voltage);
//     // CONSOLE_SERIAL.println("V");
//   } else {
//     CONSOLE_SERIAL.println("Error reading voltage");
//   }
//   return voltage;
// }

// float UART::current(){
//   float current = pzem.current();
//   if (current != NAN) {
//     // CONSOLE_SERIAL.print("Current: ");
//     // CONSOLE_SERIAL.print(current);
//     // CONSOLE_SERIAL.println("A");
//   } else {
//     CONSOLE_SERIAL.println("Error reading current");
//   }
//   return current;

// }

// float UART::power(){
//     float power = pzem.power();
//   if (power != NAN) {
//     // CONSOLE_SERIAL.print("Power: ");
//     // CONSOLE_SERIAL.print(power);
//     // CONSOLE_SERIAL.println("W");
//   } else {
//     CONSOLE_SERIAL.println("Error reading power");
//   }
//   return power;
// }