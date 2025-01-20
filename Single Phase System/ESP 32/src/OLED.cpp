#include "OLED.h"
#define SCREEN_WIDTH 128 // OLED display width, in pixels
#define SCREEN_HEIGHT 64 // OLED display height, in pixels
#define SCREEN_ADDRESS 0x3C // Address 0x3D for 128x64
#define SDA 17 
#define SCL 16

static I2C_Dev *instance = NULL;


I2C_Dev::I2C_Dev(){
    Wire.begin(SDA, SCL, 100000);
    instance = this;
}



void I2C_Dev:: initRTC(){
    
    if (!rtc.begin()){
    Serial.println("RTC not detected");
    while (1);
   }
    // rtc.adjust(DateTime(__DATE__, __TIME__));
    Serial.println("RTC ready");

}

String I2C_Dev:: updateTime(){
    DateTime now = rtc.now();
    // Serial.println(now.timestamp());
    return now.timestamp();
}

void I2C_Dev:: initOLED(){
    
    display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
    if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
    }
    delay(2000);
    display.clearDisplay();               // Clear display buffer
    display.setTextSize(1);             // Set text size
    display.setTextColor(WHITE);          // Set text color
    display.setCursor(0, 10);              // Define position
    display.println("RTC Clock");     // Display static text
    display.display();                    // Display the text and shape on the screen

    
}

void I2C_Dev:: displayTime(){

    DateTime now = rtc.now();

    // Serial.println(now.timestamp());
    display.clearDisplay();
    display.setTextSize(0.5);
    display.setCursor(0, 30);
    display.println("RTC Clock");     // Display static text
    display.println(now.timestamp());
    display.display();
    delay(5000);
}