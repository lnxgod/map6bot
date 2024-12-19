import re
import csv
import io
import sys
import os.path
import smtplib
import datetime
import argparse

import datazap_log_uploader
from myconfig import *

zerocounter = 0
current_time = datetime.datetime.today()
allmaps = set()

boostdev_counter = 0
throttleclose_count_by_gear = {}
fuel_trim_issues = []  # To store all fuel trim messages and only report if there are 5 or more

def check_timing(mythrottle, mypedal, myign1, myign2, myign3, myign4, myign5, myign6, myrpm, mytimestamp, mytrigger, afr2, mph):
    global zerocounter
    output = io.StringIO()

    if afr2 > 10:
        # 6-cylinder logic
        myigndev = myign2 + myign3 + myign4 + myign5 + myign6
        if mythrottle > 95 and mypedal > 96:
            if 6.5 < myigndev < ((myign1 - 6.5) * 6):
                print(f"Timing Deviation Detected at {mytimestamp} RPM: {myrpm} Correction: {myigndev}", file=output)
                print(f"IGN1: {myign1}, IGN2: {myign2}, IGN3: {myign3}, IGN4: {myign4}, IGN5: {myign5}, IGN6: {myign6}", file=output)
    else:
        # 4-cylinder logic
        myigndev = myign2 + myign3 + myign4
        if mythrottle > 95 and mypedal > 96:
            if 3.5 < myigndev < ((myign1 - 3) * 4):
                print("(4Cyl Mode) Timing Deviation Detected - Consider a lower map if you see lots of this", file=output)
                print(f"{mytimestamp} RPM: {myrpm} Correction: {myigndev}", file=output)
                print(f"IGN1: {myign1}, IGN2: {myign2}, IGN3: {myign3}, IGN4: {myign4}", file=output)

            if myign1 < 0.01 and mph > 25:
                zerocounter += 1
                if zerocounter > 3:
                    print(f"Timing is Crashing to zero at and before {mytimestamp} RPM:{myrpm}", file=output)

    return output.getvalue()

def map_lower_check(timing_out, map_value):
    output = io.StringIO()
    line_count = timing_out.count('\n')
    if line_count > 10 and map_value > 2:
        print("+----------------------------------+", file=output)
        print("|                                  |", file=output)
        print("|  Consider Lowering Your Map!     |", file=output)
        print("|                                  |", file=output)
        print("+----------------------------------+", file=output)
    return output.getvalue()

def check_trims(mythrottle, mypedal, myrpm, mytimestamp, mytrims, mytrims2, myafr1, myafr2):
    # Collect fuel trim issues; only report if >=5 at the end
    myspread = mytrims2 - mytrims
    messages = []

    if mythrottle > 95 and myspread > 10:
        messages.append(f"Fuel Trim separation detected rpm:{myrpm} trim1:{mytrims} trim2:{mytrims2} TS:{mytimestamp} Spread:{myspread} afr1:{myafr1} afr2:{myafr2}")

    if mythrottle > 95 and mytrims > 50:
        messages.append(f"High Fuel Trim Detected NORMAL FOR E30 / map3 bad for meth {mytrims} {mytrims2} RPM:{myrpm}")

    if mythrottle > 95 and mytrims < 7:
        messages.append(f"Low Fuel Trim Detected watch for frozen trims {mytrims}")

    fuel_trim_issues.extend(messages)
    return ""

def check_hpfp(mythrottle, mypedal, myrpm, mytimestamp, myfp_h):
    output = io.StringIO()
    if myfp_h == 0:
        return output.getvalue()

    if mythrottle > 95 and mypedal > 90 and myfp_h < 10:
        print(f"HPFP Issues Consider less E85! Detected at Timestamp {mytimestamp} RPM:{myrpm} FP:{myfp_h}", file=output)
    return output.getvalue()

def check_throttle_close(mythrottle, mypedal, myrpm, myboost, myboost2, mytimestamp, mygear):
    global throttleclose_count_by_gear
    output = io.StringIO()
    if mypedal > 95 and myrpm > 4000:
        if mythrottle < 85:
            if mygear not in throttleclose_count_by_gear:
                throttleclose_count_by_gear[mygear] = 0
            throttleclose_count_by_gear[mygear] += 1

            if throttleclose_count_by_gear[mygear] >= 3:
                print(f"Throttle Close Detected (PADDLE SHIFT INSTEAD) TS:{mytimestamp} RPM:{myrpm} Gear:{mygear} Throttle:{mythrottle} Pedal:{mypedal}", file=output)
                if (myboost - myboost2) > 3:
                    print(f"Large boost drop Detected rpm:{myrpm} boost1:{myboost} boost2:{myboost2}", file=output)
    return output.getvalue()

def check_meth_flow(mythrottle, mypedal, myrpm, myboost, mytimestamp, mymeth, mytriggercount):
    output = io.StringIO()
    if mymeth == 0:
        return output.getvalue()

    if mypedal > 95 and mymeth < 90 and mytriggercount > 1 and myboost > 10:
        print(f"Meth Flow issue Detected FIX THIS FIRST!!!!! TS:{mytimestamp} RPM:{myrpm} Boost:{myboost} Meth Flow:{mymeth}", file=output)
    return output.getvalue()

def check_boost_deviation(mythrottle, mypedal, myboost, myboost2, mytimestamp):
    global boostdev_counter
    output = io.StringIO()
    if mythrottle > 95 and (myboost - myboost2) > 1.9:
        boostdev_counter += 1
        if boostdev_counter > 4:
            print(f"Boost1/Boost2 Deviation B1:{myboost} B2:{myboost2} Diff:{myboost - myboost2} TS:{mytimestamp}", file=output)
    return output.getvalue()

def check_4cyl_data_integrity(mythrottle, mypedal, afr2, trims2, rpm, timestamp):
    # No AFR2/TRIM2 warnings
    output = io.StringIO()
    return output.getvalue()

def check_vin(myvin, my_clients):
    output = io.StringIO()
    if myvin in my_clients:
        print(f"Thank you {my_clients[myvin]} for being a paying supporter! Your Gratuity is appreciated!", file=output)
    else:
        print("I provide my services free of charge, Please consider donating to help support my ongoing efforts!", file=output)
    return output.getvalue()

def check_email(myemail, my_clients):
    output = io.StringIO()
    reemail = re.findall(r"[a-z0-9.\-+_]+@[a-z0-9.\-+_]+\.[a-z]+", myemail.lower())
    if not reemail:
        print("No valid email found", file=output)
        return output.getvalue()
    email = reemail[0]

    if email in my_clients:
        print(f"Thank you {my_clients[email]} for being a paying supporter! Your Gratuity is appreciated!", file=output)
    else:
        print("Welcome to map6bot! For info & support visit www.charitycase.net. For enhancements email bill.hatzer@gmail.com or FB. High demand: paying supporters prioritized.", file=output)
    return output.getvalue()

def check_boost_limit(myboostlimit, cyl):
    output = io.StringIO()
    if cyl > 4 and myboostlimit > 25.1:
        print("Please Consider Lowering your Boost Limit", file=output)
        print(f"Current Limit:{myboostlimit}, drop below 25psi", file=output)
    if cyl == 4 and myboostlimit > 26:
        print("Please Consider lowering your boost limit", file=output)
        print(f"Current Limit:{myboostlimit}, drop below 26psi", file=output)
    return output.getvalue()

def check_iat(myrpm, mythrottle, mypedal, myiat):
    output = io.StringIO()
    if myrpm > 2500 and mythrottle > 95 and myiat > 118:
        print(f"Heat Soak Detected! Consider Meth/FMIC or cooling off. RPM:{myrpm} IAT:{myiat}", file=output)
    return output.getvalue()

def check_firmware(firmwareversion):
    output = io.StringIO()
    if firmwareversion < 20:
        print("UPGRADE TO THE LATEST FIRMWARE!", file=output)
    return output.getvalue()

def lap3_parse(mysender, mylog):
    datazap_link = datazap_log_uploader.upload_log(mylog, mysender, str(current_time), datazap_user, datazap_password)
    subject = f"Data Log Report for {mysender}"
    body = f"Lap3 support is ALPHA. Please send more examples. Starting Report:{datazap_link}"
    send_email(mysender, subject, body)

def send_email(recipient, subject, body):
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.ehlo()
        server.login(gmail_user, gmail_password)
    except Exception as e:
        print(f"Could not connect to email server: {e}")
        return

    sent_from = gmail_user
    to = ['bill.hatzer@gmail.com', recipient]
    email_text = f"From: {sent_from}\nTo: {', '.join(to)}\nSubject: {subject}\n\n{body}\n"
    try:
        server.sendmail(sent_from, to, email_text)
        server.close()
        print('Email Sent!!!')
    except Exception as e:
        print(f"Something went wrong sending email: {e}")

class LogCheck:
    def __init__(self, logFile, sender, my_clients):
        self.logFile = logFile
        self.sender = sender
        self.my_clients = my_clients

    def my_log(self):
        if not os.path.exists(self.logFile) or not os.path.isfile(self.logFile):
            print(f"File {self.logFile} does not exist.")
            sys.exit(1)

        with open(self.logFile) as csvfile:
            mycsv = csv.reader(csvfile, delimiter=',')
            row1 = next(mycsv)
            if "Module::" in row1[0]:
                print("Lap3 Mode detected.")
            elif "Firmware" in row1[0]:
                print("JB4 mode detected.")
            else:
                print("Unknown log format")

    def parse_log(self):
        global fuel_trim_issues
        if not os.path.exists(self.logFile) or not os.path.isfile(self.logFile):
            print(f"File {self.logFile} does not exist.")
            sys.exit(1)

        with open(self.logFile) as csvfile:
            mycsv = csv.reader(csvfile, delimiter=',')
            row1 = next(mycsv)
            row2 = next(mycsv)
            row3 = next(mycsv)
            row4 = next(mycsv)
            row5 = next(mycsv)

            if "Module::" in row1[0]:
                lap3_parse(self.sender, self.logFile)
                sys.exit(0)

            emailOut = check_email(self.sender, self.my_clients)
            firmware = row2[0]
            safety_code = row4[11]

            safety_map = {
                '1': 'Boost over safety',
                '2': 'AFR Lean',
                '3': 'Fuel Pressure Low',
                '4': 'Meth Flow Low'
            }
            safety = safety_map.get(str(safety_code), 'Fuel Trim Variance')

            boostlimit = float(row4[0])
            vin = row2[12]

            firmwarever = int(firmware.split('/')[1])
            firmwarecheck = "\nFirmware Check\n----------------------\n"
            firmwarecheck += check_firmware(firmwarever)

            vinOut = check_vin(vin, self.my_clients)
            boostOut = "\nBoost Safety Check\n---------------------------\n"
            boostOut += check_boost_limit(boostlimit, 6)

            iatOut = '\nIAT\n-------------------\n'
            timingOut = '\nTiming\n----------------\n'
            hpfpOut = '\nHPFP Report\n--------------------\n'
            throttlecloseOut = "\nThrottle Report\n-----------------\n"
            methflowOut = "\nMethFlowReport\n-----------------\n"
            boostdevOut = "\nBoost Deviations\n--------------------\n"
            trimsOut = "\nFuel Trims\n-------------------------\n"
            integrityOut = "\n4Cyl Data Integrity\n-------------------------\n"

            loopcount = 0
            triggercount = 4

            for row in mycsv:
                loopcount += 1
                try:
                    timestamp = float(row[0])
                    rpm = float(row[1])
                    ecu_psi = float(row[2])
                    target = float(row[3])
                    boost = float(row[4])
                    pedal = float(row[5])
                    iat = float(row[6])
                    fuelen = float(row[7])
                    wgdc = float(row[8])
                    throttle = float(row[9])
                    fp_h = float(row[10])
                    ign_1 = float(row[11])
                    avg_ign = float(row[12])
                    calc_torque = float(row[13])
                    trims_val = float(row[14])
                    dme_bt = float(row[15])
                    meth = float(row[16])
                    fp_l = float(row[17])
                    afr = float(row[18])
                    gear = float(row[19])
                    ff = float(row[20])
                    load = float(row[21])
                    clock = float(row[22])
                    map_val = float(row[23])
                    afr2 = float(row[24])
                    ign_2 = float(row[25])
                    ign_3 = float(row[26])
                    ign_4 = float(row[27])
                    ign_5 = float(row[28])
                    ign_6 = float(row[29])
                    oilf = float(row[30])
                    waterf = float(row[31])
                    transf = float(row[32])
                    e85 = float(row[33])
                    boost2 = float(row[34])
                    trims2 = float(row[35])
                    mph = float(row[36])

                    allmaps.add(int(map_val))

                    datazap_notes = (f"Time:{current_time} ][ Firmware:{firmware} ][ Safety:{safety} ][ Map:{allmaps}")

                    iatOut += check_iat(rpm, throttle, pedal, iat)
                    timingOut += check_timing(throttle, pedal, ign_1, ign_2, ign_3, ign_4, ign_5, ign_6, rpm, timestamp, triggercount, afr2, mph)
                    hpfpOut += check_hpfp(throttle, pedal, rpm, timestamp, fp_h)
                    throttlecloseOut += check_throttle_close(throttle, pedal, rpm, boost, boost2, timestamp, gear)
                    methflowOut += check_meth_flow(throttle, pedal, rpm, boost, timestamp, meth, triggercount)
                    boostdevOut += check_boost_deviation(throttle, pedal, boost, boost2, timestamp)
                    check_trims(throttle, pedal, rpm, timestamp, trims_val, trims2, afr, afr2)
                    integrityOut += check_4cyl_data_integrity(throttle, pedal, afr2, trims2, rpm, timestamp)

                except ValueError:
                    continue

            MapOut = map_lower_check(timingOut, map_val)

            # Only report fuel trim issues if there are >= 5
            if len(fuel_trim_issues) >= 5:
                for issue in fuel_trim_issues:
                    trimsOut += issue + "\n"
            else:
                trimsOut += "No significant Fuel Trim issues detected.\n"

            print("Notes Box for Datazap.me")
            print("datazap url for viewing logs")
            print(vinOut)
            print(firmwarecheck)
            print("REPORT BELOW")
            print(boostOut)
            print(iatOut)
            print(hpfpOut)
            print(throttlecloseOut)
            print(methflowOut)
            print(boostdevOut)
            print(trimsOut)
            print(integrityOut)

            datazap_link = datazap_log_uploader.upload_log(self.logFile, self.sender, datazap_notes, datazap_user, datazap_password)
            part_url = '?log=0&data=1-3-4-5-9-11-14-18-23-25-26-27-28-29'
            new_url = datazap_link + part_url

            subject = f"Data Log Report for {self.sender}"
            body = (
                f"{emailOut} This tool is a beta and may produce false positives. "
                f"Timely assistance is not guaranteed. Contact: bill.hatzer@gmail.com or Facebook. "
                f"Starting Report: {new_url} {firmwarecheck}{boostOut}{iatOut}{hpfpOut}{throttlecloseOut}{methflowOut}{boostdevOut}{trimsOut}{timingOut}{MapOut}{integrityOut}"
            )

            send_email(self.sender, subject, body)

def main():
    parser = argparse.ArgumentParser(description="Parse a JB4 or LAP3 log and send an email report.")
    parser.add_argument('--file', '-f', required=True, help='Path to the log file to parse')
    parser.add_argument('--email', '-e', default='bill.hatzer@gmail.com', help='Recipient email address (default: bill.hatzer@gmail.com)')
    args = parser.parse_args()

    # Ensure my_clients is defined in myconfig or here
    # Example:
    # my_clients = {
    #     "email@example.com": "Client Name",
    # }

    log_checker = LogCheck(args.file, args.email, my_clients)
    log_checker.parse_log()

if __name__ == "__main__":
    main()
