#include "UART.h"
#include "Arduino.h"

UART *uart;
#define CONSOLE_SERIAL Serial
// PZEM004Tv30 pzem(PZEM1_SERIAL,RX1_PIN, TX1_PIN); 
// PZEM004Tv30 pzem(PZEM2_SERIAL,RX1_PIN, TX1_PIN); 


void initUART(){
  uart = new UART();

}
void setup() {
  CONSOLE_SERIAL.begin(115200);
  initUART();
}

void loop() {
  float current= uart->current();
  float voltage= uart->voltage();
  float power = uart->power();
  CONSOLE_SERIAL.print(current);
  CONSOLE_SERIAL.print(voltage);
  CONSOLE_SERIAL.print(power);

}