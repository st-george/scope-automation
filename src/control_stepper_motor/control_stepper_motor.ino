/*
    Stepper motor and canera control through serial communication

    Reads the serial port for commands:
    - M<steps> to move the attached stepper motor, negative values go backwards
    - S to release the camera shutter
    - F to focus camera (camera is woken up if asleep)

    Settings:
    * Communication through USB serial at speed 115200
    * Adafruit motor shield v2.3
    * Stepper motor connected to motor shield port 2
        * Motor RPM is hard-coded to 200
        * Supports single stepping
    * Camera focus shield must support focusing by setting pin 2 up, and releasing the shutter by setting pin 13 up

*/

#include <Wire.h>
#include <Adafruit_MotorShield.h>

int CAMERA_FOCUS_PIN = 2;
int CAMERA_SHUTTER_PIN = 13;

Adafruit_MotorShield AFMS = Adafruit_MotorShield(); 

Adafruit_StepperMotor *stepper = AFMS.getStepper(200, 2);

long steps  = 0;

int incomingByte;
int command;

void setup_camera() {
  pinMode(CAMERA_FOCUS_PIN, OUTPUT);
  pinMode(CAMERA_SHUTTER_PIN, OUTPUT);
}

void setup() {
  setup_camera();
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
    delay(1000);
  }
}

void read_command() {
  incomingByte = Serial.read();

  switch (incomingByte) {
    case 'M':
      steps = Serial.parseInt();
      command = incomingByte;
      break;
    case 'F':
    case 'S':
      command = incomingByte;
      break;
    default:
      command = -1;
      Serial.print("E1 ");
      Serial.println(incomingByte, DEC);
      break;
       
  }
  incomingByte = Serial.read();
  while (incomingByte == '\r' || incomingByte == '\n') {
    incomingByte = Serial.read();  
  }
}

void motor_move() {
  if (steps != 0) {

    if (steps > 0) {
      stepper->step(steps, FORWARD, SINGLE);
    } else {
      stepper->step(-steps, BACKWARD, SINGLE);
    }
  }

  Serial.print("OK M");
  Serial.println(steps);
}

void camera_focus() {
  digitalWrite(CAMERA_FOCUS_PIN, HIGH);
  delay(250);
  digitalWrite(CAMERA_FOCUS_PIN, LOW);
  Serial.println("OK F");
}

void camera_shutter() {
  digitalWrite(CAMERA_SHUTTER_PIN, HIGH);
  delay(250);
  digitalWrite(CAMERA_SHUTTER_PIN, LOW);

  Serial.println("OK S");
}

void loop() {
  
  if (Serial.available() > 0) {

      read_command();

      if (command == 'M') {

        motor_move();
  
      } else if (command == 'F') {
        camera_focus();
      } else if (command == 'S') {
        camera_shutter();
      } else if (command != -1) {
        Serial.println("E2");
      }
  }
}
