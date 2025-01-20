#ifndef UART_H_
#define UART_H_

#include <PZEM004Tv30.h>
#include <tuple>
#define RX1_PIN 33
#define TX1_PIN 32
#define RX2_PIN 26
#define TX2_PIN 25
#define CONSOLE_SERIAL Serial
#define PZEM2_SERIAL Serial1
#define PZEM1_SERIAL Serial2

class UART{
private:
    PZEM004Tv30 pzem = PZEM004Tv30(PZEM2_SERIAL,RX1_PIN,TX1_PIN); 
    
public:
    UART();
    float voltage();
    float current();
    float power();
    std::tuple<float,float,float> results();
};



#endif 