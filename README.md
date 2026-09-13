<img width="586" height="671" alt="kimmyscore" src="https://github.com/user-attachments/assets/8a034068-da7f-47bb-af10-423387b0e5ea" />


# Kimmy Score

Kimmy Score is a method that will allow the Arcade1up Dragon's Lair Scoreboard to communicate with Hypseus.

# How to get scoreboard ready for PC communications. 

This will require modification of your scoreboard *DO AT YOUR OWN RISK*.

You will need a CP2102 USB to TTL Module Serial Converter Adapter.

The yellow wire of the scoreboard RX will need to be connected to the TX of the CP2102.

The black wire (ground) will need to be connected as well.

DO NOT USE the 5v from the CP2102 to power the scoreboard a separate 5v power supply is recommended for the scoreboard itself.

When connecting power use the red wire from the scoreboard and connect the black wire (ground) as well having it still connected to the ground of the CP2102.

# Wiring Schematic

This is how the scoreboard should be wired to the CP2102 and power supply.

<img width="1018" height="971" alt="wiringschematic" src="https://github.com/user-attachments/assets/a28410dc-7f0f-4861-b452-ee39486d5890" />

The TX of the CP2102 should be connected to the `Yellow` wire of the scoreboard `RX`.

DO NOT POWER FROM CP2102 use an external 5 volt power source as shown.

The `Brown` wire TX is on the scoreboard is not used.

The `Black` wire (ground) should be connected to the scoreboard as shown along with power sources ground wire being tied into as well.

5v is only assumed to be the correct voltage at this point until confirmed from original PCB

*MOD AT YOUR OWN RISK*

# Programs required

You will need [com0com](https://sourceforge.net/projects/com0com/) installed to create a virtual pair of com ports for the script and Hypseus to interact with each other.

Once com0com is configured run the kimmyscore.py script and launch Hypseus with settings for usbscoreboard communication.

The script will have the CP2102 set as com3 and Hypseus should be configured to use com4.

Scoreboard should begin working once Hypseus begins sending data.

# Hypseus requirements

Dragon's Lair or Space Ace configured (SPACE ACE FTW).

Ensure that you have Hypseus lauching with `-usbscoreboard COM 4 19200`

`"C:\Hypseus Singe\hypseus.exe" ace vldp -framefile "C:\Daphne\vldp_dl\ace\ace.txt" -usbscoreboard COM 4 19200`

Enjoy!

# AI Disclosure

The python script was created with the help of AI

If you are not comfortable with the use of AI then this project is not for you
