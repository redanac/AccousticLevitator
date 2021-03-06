#!/usr/bin/python
import math

class Controller():
    def __init__(self, ports = []):
        self.ports = ports
        pass
            
    def __enter__(self):
        import serial
        import os

        if len(self.ports) == 0:
            if os.name == "nt":
                self.ports = ["COM"+str(i) for i in range(1, 9)]
                #self.ports = ["COM3"]
            else:
                self.ports = ["/dev/ttyUSB"+str(i) for i in range(0, 9)]

        self.outputs = 0
        for port in self.ports:
            try:
                print("Trying to connect to board on "+port)
                self.com = serial.Serial(port=port, baudrate=460800, timeout=0.5)
                self.com.reset_input_buffer()
                print("Connected, testing for controller")
                self.outputs = self.getOutputs()
                self.version = self.getVersion()
                print("Checking firmware version",self.version)
                #if (self.version != 7):
                    #raise Exception("Unexpected board version",self.version)
                print("Connected successfully to board with "+str(self.outputs)+" outputs")
                break
            except Exception as e:
                print(e)
                self.com = None
        if (self.com == None):
            raise Exception("Failed to open communications!")
            
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        #for i in range(self.outputs):
        #    self.disableOutput(i)
        self.com.close()        

    def getOneWordReply(self, cmd):
        self.sendCmd(cmd)
        ack = bytearray(self.com.read(1))
        if (len(ack) != 1):
            raise Exception("Failed to read one word")
        return ack[0]

    def getOutputs(self):
        return self.getOneWordReply(bytearray([0b11000000,0,0]))

    def getVersion(self):
        return self.getOneWordReply(bytearray([0b11101000,0,0]))
    
    def sendCmd(self, bytestream):
        #Serial communication is carried out using 8 bit/byte
        #chunks. To be able to communicate all the data we need, we
        #use commands composed of 3 bytes. We use the highest bit of
        #each byte to denote if it is the first byte in a command.
        #The remaining bytes must not have the uppermost bit set (to
        #prevent errors in communication causing the controller to
        #assume they are the start of a command), thus only 21bits of
        #information are available for each command.

        # #The structure of a command
        #   23  22  21  20  19  18  17  16  15  14  13  12  11  10  9   8   7   6   5   4   3   2   1   0
        # | 1 | X | X | X | X | X | X | X | 0 | X | X | X | X | X | X | X | 0 | X | X | X | X | X | X | X |
        # 
        self.com.write(bytestream)
        ack = bytearray(self.com.read(3))
        if bytestream != ack:
            print ("Sent", repr(bytestream), "but got", ack)
        
    def loadOffsets(self):
        self.sendCmd(bytearray([0b11110000, 0, 0]))

    def setOffset(self, clock, offset, enable=True):
        # #The structure of the command
        #   23  22  21  20  19  18  17  16  15  14  13  12  11  10  9   8   7   6   5   4   3   2   1   0
        # | 1 | 0 | 0 | X | X | X | X | X | 0 | X | X | C | Z | Y | Y | Y | 0 | Y | Y | Y | Y | Y | Y | Y |
        #  X = 7 bit clock select
        #  Y = 10 bit half-phase offset
        #  Z = phase of first oscillation
        #  C = Output enable bit
        if clock > 0b01111111:
            raise Exception("Clock selected is too large!")
        
        if isinstance(offset, float):
            offset = int(1250 * (offset / (2 * math.pi)))

        sign = 0
        offset = offset % 1250
        if offset > 624:
            sign = 1
            offset = offset - 624

        # Place the first 7 bits of the offset into the low_offset byte
        low_offset =  offset & 0b01111111
        # Place the remaining 3 bits of the offset, plus the sign bit, into the high offset
        high_offset = ((offset >> 7) & 0b00000111) + (sign << 3)

        #The command byte has the command bit set, plus 5 bits of the clock select
        b1 = 0b10000000 | (clock >> 2)
        #The next bit has the output enable bit set high, plus the last two bits of the clock select, and the high offset bits
        enable_bit = 0b00010000
        if not enable:
            enable_bit = 0b00000000
        
        b2 = enable_bit | ((clock & 0b00000011)<<5)  | high_offset
        #The last byte contains the low offset bits
        b3 = low_offset
        cmd = bytearray([b1, b2, b3])
        #print(list(map(bin,cmd)))
        self.sendCmd(cmd)

    def setOutputDACPower(self, power):
        # #The structure of the command
        #   23  22  21  20  19  18  17  16  15  14  13  12  11  10  9   8   7   6   5   4   3   2   1   0
        # | 1 | 1 | 1 | X | X | X | X | X | 0 | X | X | X | X | X | X | Y | 0 | Y | Y | Y | Y | Y | Y | Y |
        #  X = UNUSED
        #  Y = 7 bit DAC value
        if power > 256: #Not a mistake! the DAC goes from 0-256, not 255!
            raise Exception("Power selected is too large!")

        cmd = bytearray([0b11100000, 0b00000011 & (power >> 7), 0b01111111 & power])
        self.sendCmd(cmd) 

    def setOutputDACDivisor(self, divisor):
        # #The structure of the command
        #   23  22  21  20  19  18  17  16  15  14  13  12  11  10  9   8   7   6   5   4   3   2   1   0
        # | 1 | 0 | 1 | Y | Y | Y | Y | Y | 0 | Y | Y | Y | Y | Y | Y | Y | 0 | Y | Y | Y | Y | Y | Y | Y |
        #  X = UNUSED
        #  Y = 7 bit DAC value
        if divisor > 0b1111111111111111111:
            raise Exception("Divisor selected is too large!")
        if divisor < 50:
            raise Exception("You'll burn out the board if this divisor is too low (<50).")
        cmd = bytearray([0b10100000 | (0b00011111 & (divisor >> 14)), 0b01111111 & (divisor >> 7), 0b01111111 & divisor])
        self.sendCmd(cmd) 

    def setOutputDACFreq(self, freq):
        self.setOutputDACPower(128) #50% duty cycle, turns the board off and on for equal amounts of time
        divisor=int(5e7/(4*freq)+1)
        return self.setOutputDACDivisor(divisor)
        
    def disableOutput(self, clock):
        self.setOffset(clock, 0, enable=False)
        
    def benchmark(self):
        import timeit
        start = timeit.default_timer()
        NTests = 1000
        outputs = self.getOutputs()
        for i in range (NTests):
            for i in range(outputs):
                ctl.setOffset(i, 0)
            ctl.loadOffsets()
        end = timeit.default_timer()
        print( "Benchmark - Pattern update at ", NTests/float(end-start), "Hz")

    def benchmarkPower(self):
        import timeit
        start = timeit.default_timer()
        NTests = 1000
        outputs = self.getOutputs()
        for i in range (NTests):
            self.setOutputDACDivisor(0)
        end = timeit.default_timer()
        return NTests/float(end-start)
        
    def syncResets(self):
        self.com.write(bytearray([0b11110000]))
        self.com.write(bytearray([0b11110001]))
