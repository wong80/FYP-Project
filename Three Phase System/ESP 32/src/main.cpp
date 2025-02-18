#include "Arduino.h"
#include "Network.h"
#include "OLED.h"
#include "SD_Card.h"
#include "UART.h"

Network *network;
I2C_Dev *dev;
SDCARD *sdcard;
UART *uart;
float voltage1,current1,power1,voltage2,current2,power2,voltage3,current3,power3;



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
  Serial.begin(115200);
  initNetwork();
  initUART();
  initI2C_Dev();
  initSD_Card();
  sdcard->FileHeader();
}

void loop(){
  
  
  String time = dev->updateTime();

  std::tie(voltage1,current1,power1,voltage2,current2,power2,voltage3,current3,power3) = uart->results();
  dev->displayStatus(voltage1,voltage2,voltage3);
  sdcard -> logData(time,voltage1,current1,power1,voltage2,current2,power2,voltage3,current3,power3);
  network->RTDBUpdate(time,voltage1,current1,power1,voltage2,current2,power2,voltage3,current3,power3);
  delay(1000*60);
}