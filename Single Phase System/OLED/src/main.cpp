#include "OLED.h"
#include "Arduino.h"

I2C_Dev *dev;

void initI2C_Dev(){
  dev = new I2C_Dev();
  dev->initRTC();
  dev->initOLED();
}

void setup() {

  Serial.begin(115200);
  
  initI2C_Dev();


}


void loop() {
  dev->displayTime();

}