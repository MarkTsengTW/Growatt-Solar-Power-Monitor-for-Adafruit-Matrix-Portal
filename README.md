GROWATT SOLAR POWER MONITOR FOR ADAFRUIT MATRIX PORTAL

Monitor your solar power production from your Matrix Portal.
Know when to run your washing machine, air fryer, electric weed whacker, etc.
Use less power from the grid. Save money, and the planet while you're at it.

This is a hobby project I made while learning to code. I'm very happy to hear about
any issues and mistakes because I'm trying to improve.

SETUP
You will need to ensure you have adafruit_hashlib installed on your MatrixPortal.
You will need a recent version of adafruit_requests too. If you have an older version
frozen into your firmware, you may need to put the recent version in the root of
the CircuitPython drive to ensure it loads in preference to the frozen version.
You will also need to add growatt_username and growatt_password to your secrets.py
(If you have a specific plant you want to check, then put it into secrets.py as
growatt_plant_id

STATUS NEOPIXEL
Green = loading; yellow = preparing API call or processing API response;
blue = making API call; red = exception handling.

CREDITS
This code is based on indykoning's Growatt Server https://github.com/indykoning
I learned a lot adapting this code for the Matrix Portal.
Credit also to ajs256 for the efficient graphics setup code.
Credit to Tekktrik for assistance modifying adafruit_requests to handle multiple cookies.

FEEDBACK AND ISSUES
This version is fairly stable but can crash occasionally. I'm still looking into the cause.
Happy to hear about issues and features that would be useful to add.
E.g. I would like to have some kind of graphic to make it more appealing. A sun, or a leaf
or something like that.
