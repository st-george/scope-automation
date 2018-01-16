/*
	Stepper motor control through serial communication

	Reads the serial port for commands to move the attached stepper motor

	Settings:
	* Communication through USB serial at speed 115200
	* Adafruit motor shield v2.3
	* Stepper motor connected to motor shield on port 2
        * Motor RPM is hard-coded to 200
        * Supports single stepping

*/

#include <Wire.h>
#include <Adafruit_MotorShield.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_MotorShield AFMS = Adafruit_MotorShield(); 

Adafruit_StepperMotor *stepper = AFMS.getStepper(200, 2);

long steps  = 0;

void setup() {
  AFMS.begin();
  stepper->setSpeed(10); // RPM
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for serial port to connect. Needed for native USB port only
  }
  
  establishContact();
}

void establishContact() {
  while (Serial.available() <= 0) {
    Serial.println("HELLO");
    delay(500);
  }
}

void loop() {
  
  if (Serial.available() > 0) {
  
    steps = Serial.parseInt();
    if (steps != 0) {

      if (steps > 0) {
        stepper->step(steps, FORWARD, SINGLE);
      } else {
        stepper->step(-steps, BACKWARD, SINGLE);
      }
    
      Serial.print(steps);
      Serial.println(" OK");
    }
  }
}
