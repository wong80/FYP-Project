#include "UART.h"

static UART *instance = NULL;

UART::UART(){
    instance = this;
}

std::tuple<float,float,float> UART::results(){
  return std::make_tuple(pzem.voltage(), pzem.current(),pzem.power());
}

float UART::voltage(){
  float voltage = pzem.voltage();
  if (voltage != NAN) {
    // CONSOLE_SERIAL.print("Voltage: ");
    // CONSOLE_SERIAL.print(voltage);
    // CONSOLE_SERIAL.println("V");
  } else {
    CONSOLE_SERIAL.println("Error reading voltage");
  }
  return voltage;
}

float UART::current(){
  float current = pzem.current();
  if (current != NAN) {
    // CONSOLE_SERIAL.print("Current: ");
    // CONSOLE_SERIAL.print(current);
    // CONSOLE_SERIAL.println("A");
  } else {
    CONSOLE_SERIAL.println("Error reading current");
  }
  return current;

}

float UART::power(){
    float power = pzem.power();
  if (power != NAN) {
    // CONSOLE_SERIAL.print("Power: ");
    // CONSOLE_SERIAL.print(power);
    // CONSOLE_SERIAL.println("W");
  } else {
    CONSOLE_SERIAL.println("Error reading power");
  }
  return power;
}