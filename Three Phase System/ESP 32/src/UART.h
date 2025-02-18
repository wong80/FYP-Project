#ifndef UART_H_
#define UART_H_

#include <PZEM004Tv30.h>
#include <tuple>
#define RX1_PIN 33
#define TX1_PIN 32
#define RX2_PIN 26
#define TX2_PIN 25
#define RX3_PIN 13
#define TX3_PIN 12
// #define CONSOLE_SERIAL Serial
#define PZEM1_SERIAL Serial
#define PZEM2_SERIAL Serial1
#define PZEM3_SERIAL Serial2


class UART{
private:
    PZEM004Tv30 pzem1 = PZEM004Tv30(PZEM1_SERIAL,RX1_PIN,TX1_PIN); 
    PZEM004Tv30 pzem2 = PZEM004Tv30(PZEM2_SERIAL,RX2_PIN,TX2_PIN); 
    PZEM004Tv30 pzem3 = PZEM004Tv30(PZEM3_SERIAL,RX3_PIN,TX3_PIN);

    
public:
    UART();

    std::tuple<float,float,float,float,float,float,float,float,float> results();

};



#endif 