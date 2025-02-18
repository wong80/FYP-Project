#ifndef OLED_H_
#define OLED_H_

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <RTClib.h>

class I2C_Dev{
private:
    Adafruit_SSD1306 display = Adafruit_SSD1306(128, 64, &Wire, -1);
    RTC_DS3231 rtc; 
public:
    I2C_Dev();
    void initRTC();
    void initOLED();
    void displayStatus(double voltage1, double voltage2, double voltage3);
    String updateTime();
};


#endif