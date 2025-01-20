#include "Arduino.h"
#include "Network.h"
#include "OLED.h"
#include "SD_Card.h"
#include "UART.h"

Network *network;
I2C_Dev *dev;
SDCARD *sdcard;
UART *uart;
float voltage,current,power;

#define CONSOLE_SERIAL Serial
PZEM004Tv30 pzem(PZEM1_SERIAL,RX1_PIN, TX1_PIN);
void initNetwork(){
  network = new Network();  
  network->initWiFi();

}

void initI2C_Dev(){
  dev = new I2C_Dev();
  dev->initOLED();
  dev->initRTC();
}

void initSD_Card(){
  sdcard = new SDCARD();
  sdcard ->initSD();
}

void initUART(){
  uart = new UART();
}
void setup(){
  CONSOLE_SERIAL.begin(115200);
  initNetwork();
  initUART();
  initI2C_Dev();
  initSD_Card();
  // sdcard->FileHeader();
}

void loop(){
  dev->displayTime();
  
  String time = dev->updateTime();

  std::tie(voltage,current,power) = uart->results();
  sdcard -> logData(time,voltage,current,power);
  network->RTDBUpdate(time,voltage,current,power);
  delay(1000);
}