<img width="586" height="671" alt="kimmyscore" src="https://github.com/user-attachments/assets/8a034068-da7f-47bb-af10-423387b0e5ea" />


# kimmy-score

Kimmy Score is a method that will allow the Arcade1up Dragon's Lair Scoreboard to communicate with Hypseus

# How to get scoreboard ready for PC communications 

This will require modification of your scoreboard *DO AT YOUR OWN RISK*

You will need a CP2102 USB to TTL Module Serial Converter Adapter

The yellow wire of the scoreboard RX will need to be connected to the TX of the CP2102

The black wire (ground) will need to be connected as well

DO NOT USE the 5v from the CP2102 to power the scoreboard a separate 5v power supply is recommended for the scoreboard itself

When connecting power use the red wire from the scoreboard and connect the black wire (ground) as well having it still connected to the ground of the CP2102

# Programs required

You will need com0com installed to create a virtual pair of com ports for the script and Hypseus to interact with each other 

Once com0com is configured run the kimmyscore.py script and launch Hypseus with settings for usbscoreboard communication

The script will have the CP2102 set as com3 and Hypseus should be configured to use com4

Scoreboard should begin working once Hypseus begins sending data

# Hypseus requirements

Dragon's Lair or Space Ace configured (SPACE ACE FTW)

Ensure that you have Hypseus lauching with -usbscoreboard COM 4 19200

ie. "C:\Hypseus Singe\hypseus.exe" ace vldp -framefile "C:\Daphne\vldp_dl\ace\ace.txt" -usbscoreboard COM 4 19200

Enjoy!
