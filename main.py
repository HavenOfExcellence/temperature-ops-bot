from api_wrapper import TelegramApiWrapper
from flask import Flask, request
import json
import logging
import lib.requests as requests
import re
from datetime import datetime, timedelta
from google.cloud import ndb

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-8s :: (%(name)s) > %(message)s'
)


# load private API tokens from file
def loadTokens():
    with open("tokens.json") as tf:
        tokens = json.load(tf)

    return tokens


# load strings from file
def loadStrings():
    with open("strings.json") as tf:
        strings = json.load(tf)

    return strings


class WebsiteStatus(ndb.Model):
    status = ndb.BooleanProperty(default=True)
    # url = ndb.StringProperty(default="https://temptaking.ado.sg")  # for debugging purposes
    skippedReminder = ndb.BooleanProperty(default=False)


class Client(ndb.Model):
    firstName = ndb.StringProperty()
    status = ndb.StringProperty(default='0')
    groupId = ndb.StringProperty()
    groupName = ndb.StringProperty()
    groupMembers = ndb.TextProperty()
    memberName = ndb.StringProperty()
    memberId = ndb.StringProperty()
    pin = ndb.StringProperty()
    temp = ndb.StringProperty()


app = Flask(__name__)
logger = logging.getLogger(__name__)

tokens = loadTokens()
strings = loadStrings()
telegramApi = TelegramApiWrapper(tokens["telegram-bot"])

#  this context will be used for the entire app instance
ndb_client = ndb.Client()
with ndb_client.context():
    wstatus = WebsiteStatus.get_or_insert('status')


def generateTemperatures():
    return [[str(x / 10), str((x + 1) / 10)] for x in range(355, 375, 2)]


def emojiTime(now):
    hour = now.hour
    minute = now.minute
    clocks = strings["clocks"]

    return clocks[round(2 * (hour + minute / 60) % 24)]


def strftime(datetimeobject, formatstring):
    formatstring = formatstring.replace("%%", "percent_placeholder")
    ps = list(set(re.findall("(%.)", formatstring)))
    format2 = "|".join(ps)
    vs = datetimeobject.strftime(format2).split("|")
    for p, v in zip(ps, vs):
        formatstring = formatstring.replace(p, v)
    return formatstring.replace("percent_placeholder", "%")


def submitTemp(client, temp):
    now = datetime.now() + timedelta(hours=8)
    if now.hour < 12:
        meridies = 'AM'
    else:
        meridies = 'PM'
    try:
        url = 'https://temptaking.ado.sg/group/MemberSubmitTemperature'
        payload = {
            'groupCode': client.groupId,
            'date': strftime(now, '%d/%m/%Y'),
            'meridies': meridies,
            'memberId': client.memberId,
            'temperature': temp,
            'pin': client.pin
        }
        r = requests.post(url, data=payload)
    except:
        # TODO: proper exception handling has to be done tbh
        return 'error'
    return r.text


@app.route('/me')
def getMe():
    resp = telegramApi.getMe()
    return resp["result"]


@app.route('/setWebhook')
def getWebhook():
    url = tokens["project-url"] + "webhook"
    resp = telegramApi.setWebhook(url)
    if resp["ok"]:
        return "webhook has been set to " + url
    else:
        return "webhook failed to set. DEBUG: " + str(resp)


# # for debugging purposes
# @app.route('/flipSwitch')
# def flipSwitch():
#     with ndb_client.context():
#         wstatus = WebsiteStatus.get_or_insert('status')
#         if wstatus.url == "https://temptaking.ado.sg":
#             wstatus.url = "https://temptaking.ado.sgs"  # force website to appear offline
#         else:
#             wstatus.url = "https://temptaking.ado.sg"
#         wstatus.put()
#         return wstatus.url


@app.route('/websiteStatus')
def websiteStatus(context=None):
    def websiteStatus():
        wstatus = WebsiteStatus.get_or_insert('status')
        try:
            requests.get("https://temptaking.ado.sg")
            if not wstatus.status:
                # restore all client statuses to their original value before updating wstatus
                all_clients = Client.query().fetch(keys_only=True)
                i = 0
                for client in all_clients:
                    key_id = client.id()
                    client = client.get()
                    if client.status.startswith("offline"):
                        client.status = client.status.split(",")[1]
                        payload = {
                            'chat_id': str(key_id),
                            'text': strings["status_online"],
                            'parse_mode': 'HTML'
                        }
                        telegramApi.sendMessage(payload)
                        client.put()
                        i += 1
                # update wstatus
                wstatus.status = True
                if wstatus.skippedReminder:
                    remind(True)
                    wstatus.skippedReminder = False
                wstatus.put()
                return "message sent to {} clients".format(str(i))
        except:
            if wstatus.status:
                wstatus.status = False
                wstatus.put()
            return "offline"
        else:
            return "online"
    if context:
        resp = websiteStatus()
    else:
        with ndb_client.context():
            resp = websiteStatus()
    return resp



@app.route('/remind')
def remind(context=None):
    def remind():
        wstatus = WebsiteStatus.get_or_insert('status')
        if not wstatus.status:
            if not wstatus.skippedReminder:
                all_clients = Client.query().fetch(keys_only=True)
                i = 0
                for client in all_clients:
                    key_id = client.id()
                    client = client.get()
                    now = datetime.now() + timedelta(hours=8)
                    if now.hour == 0 or now.hour == 12:
                        if client.status == 'endgame 1' or client.status == 'endgame 2':
                            if client.temp != 'error':
                                client.temp = 'none'
                    if client.temp == 'none':
                        temperatures = generateTemperatures()
                        text = strftime(now, strings["remind_offline"])
                        payload = {
                            'chat_id': str(key_id),
                            'text': text,
                            "parse_mode": "HTML",
                            'reply_markup': {
                                "keyboard": temperatures,
                                "one_time_keyboard": True
                            }
                        }
                        telegramApi.sendMessage(payload)
                        client.status = 'endgame 2'
                        i += 1
                    client.put()
                wstatus.skippedReminder = True
                wstatus.put()
                return 'website offline. notification sent to {} clients'.format(i)
            return "website offline"
        else:
            all_clients = Client.query().fetch(keys_only=True)
            i = 0
            for client in all_clients:
                key_id = client.id()
                client = client.get()
                now = datetime.now() + timedelta(hours=8)
                if now.hour == 0 or now.hour == 12:
                    if client.status == 'endgame 1' or client.status == 'endgame 2':
                        if client.temp != 'error':
                            client.temp = 'none'
                if client.temp == 'none':
                    temperatures = generateTemperatures()
                    if now.hour < 12:
                        if wstatus.skippedReminder:
                            text = strings["remind_delayed"] + strftime(now, strings["window_open_AM"])
                        else:
                            text = strftime(now, strings["window_open_AM"])
                    else:
                        if wstatus.skippedReminder:
                            text = strings["remind_delayed"] + strftime(now, strings["window_open_PM"])
                        else:
                            text = strftime(now, strings["window_open_PM"])
                    payload = {
                        'chat_id': str(key_id),
                        'text': text,
                        "parse_mode": "HTML",
                        'reply_markup': {
                            "keyboard": temperatures,
                            "one_time_keyboard": True
                        }
                    }
                    telegramApi.sendMessage(payload)
                    client.status = 'endgame 2'
                    i += 1
                client.put()
            return 'reminder sent to {} clients'.format(i)
    if context:
        resp = remind()
    else:
        with ndb_client.context():
            resp = remind()
    return resp


@app.route('/broadcast', methods=["POST"])
def broadcast():
    with ndb_client.context():
        all_clients = Client.query().fetch(keys_only=True)
        for client in all_clients:
            key_id = client.id()
            payload = {
                'chat_id': str(key_id),
                'text': request.get_json()['msg'],
                'parse_mode': 'HTML'
            }
            telegramApi.sendMessage(payload)
        return 'broadcast sent to ' + str(len(all_clients)) + ' clients'


@app.route('/webhook', methods=["POST"])
def webhook():
    with ndb_client.context():
        body = request.get_json()
        logging.info('request body:')
        logging.info(body)
        response = json.dumps(body)

        update_id = body['update_id']
        try:
            message = body['message']
        except:
            message = body['edited_message']
        message_id = message.get('message_id')
        date = message.get('date')
        text = message.get('text')
        fr = message.get('from')
        chat = message['chat']
        chat_id = chat['id']
        client = Client.get_or_insert(str(chat_id))

        if client.firstName != fr:
            client.firstName = fr["first_name"]
            client.put()

        # reply function used in context of this response only
        def reply(msg=None, markup=None):
            if msg:
                if markup:
                    payload = {
                        'chat_id': str(chat_id),
                        'text': msg,
                        'reply_to_message_id': str(message_id),
                        'reply_markup': markup,
                        'parse_mode': 'HTML'
                    }
                else:
                    payload = {
                        'chat_id': str(chat_id),
                        'text': msg,
                        'reply_to_message_id': str(message_id),
                        'parse_mode': 'HTML'
                    }
                resp = telegramApi.sendMessage(payload)
            else:
                logging.error('no msg specified')
                resp = None
            logging.info('send response:')
            logging.info(resp)

        # message function used in context of this response only
        def message(msg=None, markup=None):
            if msg:
                if markup:
                    payload = {
                        'chat_id': str(chat_id),
                        'text': msg,
                        'reply_markup': markup,
                        'parse_mode': 'HTML'
                    }
                else:
                    payload = {
                        'chat_id': str(chat_id),
                        'text': msg,
                        'parse_mode': 'HTML'
                    }
                resp = telegramApi.sendMessage(payload)
            else:
                logging.error('no msg specified')
                resp = None
            logging.info('send response:')
            logging.info(resp)

        def setGroupId(client, group_url):
            group_string = 'temptaking.ado.sg/group'
            if group_url.startswith(group_string):
                group_url = 'https://' + group_url
            if group_url.startswith('https://' + group_string) or group_url.startswith('http://' + group_string):
                try:
                    req_text = str(requests.get(group_url).content)
                except:
                    return 0
                if 'Invalid code' in req_text:
                    return -1

                def urlParse(text):
                    return text[text.find('{'):text.rfind('}') + 1]

                parsed_url = json.loads(urlParse(req_text))
                client.groupName = parsed_url["groupName"]
                client.groupId = parsed_url["groupCode"]
                client.groupMembers = json.dumps(parsed_url["members"])
                client.put()
                return 1
            else:
                return -1

        if text is None:
            reply(strings["no_text_error"])
            return response

        # force check website status before proceeding
        wstatus = WebsiteStatus.get_or_insert('status')
        if not wstatus.status:
            message(strings["status_offline_response"])
            # remember the client's previous status
            if not client.status.startswith("offline"):
                client.status = "offline,{}".format(client.status)
                client.put()
            return response

        if text.startswith('/'):
            if text == '/start':
                message(strings["SAF100"])
                client.status = '1'
                client.temp = 'init'
                client.put()
                return response
            elif text == '/forcesubmit':
                if client.status == 'endgame 1':
                    now = datetime.now() + timedelta(hours=8)
                    temperatures = generateTemperatures()
                    if now.hour < 12:
                        msg = strftime(now, strings["window_open_AM"])
                    else:
                        msg = strftime(now, strings["window_open_PM"])
                    markup = {
                        "keyboard": temperatures,
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
                    client.status = 'endgame 2'
                    client.put()
                    return response
            reply(strings["invalid_input"])

        elif client.status == '1':
            group_url = text
            groupFlag = setGroupId(client, group_url)
            if groupFlag == 1:
                msg = strings["group_msg"].format(client.groupName)
                markup = {
                    "keyboard": [
                        [
                            strings["group_keyboard_yes"]
                        ],
                        [
                            strings["group_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = '2'
                client.put()
            elif groupFlag == 0:
                websiteStatus(True)
                if not wstatus.status:
                    message(strings["status_offline_response"])
                    if not client.status.startswith("offline"):
                        client.status = "offline,{}".format(client.status)
                        client.put()
                else:
                    message(strings["website_error"])
            else:
                reply(strings["invalid_url"])
            return response

        elif client.status == '2':
            if text == strings["group_keyboard_yes"]:
                gm = json.loads(client.groupMembers)
                name_list = '\n'.join(
                    [str(i + 1) + '. ' + "<b>{}</b>".format(gm[i]["identifier"]) for i in range(len(gm))])
                if len(gm) > 300 or len(strings["member_msg_1"] + name_list) > 4096:
                    message(strings["member_overflow"].format(str(len(gm))))
                else:
                    msg = strings["member_msg_1"] + name_list
                    markup = {
                        "keyboard": [[item["identifier"]] for item in gm][0:300],
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
                client.status = '3'
                client.put()
                return response
            elif text == strings["group_keyboard_no"]:
                message(strings["SAF100_2"])
                client.status = '1'
                client.put()
                return response
            else:
                msg = strings["use_keyboard"]
                # TODO: put all these markups in a markups.json
                markup = {
                    "keyboard": [
                        [
                            strings["group_keyboard_yes"]
                        ],
                        [
                            strings["group_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                return response

        elif client.status == '3':
            gm = json.loads(client.groupMembers)
            try:
                index = [obj["identifier"] for obj in gm].index(text)
                client.memberId = gm[index]["id"]
                client.memberName = gm[index]["identifier"]
                client.pin = str(gm[index]["hasPin"])  # if this is False, ask the user to set a pin later

                msg = strings["member_msg_2"].format(client.memberName)
                markup = {
                    "keyboard": [
                        [
                            strings["member_keyboard_yes"]
                        ],
                        [
                            strings["member_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = '4'
            except ValueError:
                # user input does not match any identifier
                name_list = '\n'.join(
                    [str(i + 1) + '. ' + "<b>{}</b>".format(gm[i]["identifier"]) for i in range(len(gm))])
                if len(gm) > 300 or len(strings["member_msg_1"] + name_list) > 4096:
                    reply(strings["member_overflow_wrong"].format(text))
                else:
                    msg = strings["member_msg_1"] + name_list
                    markup = {
                        "keyboard": [[item["identifier"]] for item in gm],
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
            client.put()
            return response

        elif client.status == '4':
            if text == strings["member_keyboard_yes"]:
                if client.pin == 'False':
                    msg = strings["set_pin_1"].format(client.groupId)
                    markup = {
                        "keyboard": [
                            [
                                strings["pin_keyboard"]
                            ]
                        ],
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
                    client.pin = 'no pin'
                else:
                    message(strings["pin_msg_1"])
                    client.status = '5'
                client.put()
                return response
            elif text == strings["member_keyboard_no"]:
                gm = json.loads(client.groupMembers)
                name_list = '\n'.join(
                    [str(i + 1) + '. ' + "<b>{}</b>".format(gm[i]["identifier"]) for i in range(len(gm))])
                if len(gm) > 300 or len(strings["member_msg_1"] + name_list) > 4096:
                    message(strings["member_overflow"].format(str(len(gm))))
                else:
                    msg = strings["member_msg_3"] + name_list
                    markup = {
                        "keyboard": [[item["identifier"]] for item in gm],
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
                client.status = '3'
                client.put()
                return response
            elif text == strings["pin_keyboard"]:  # triggered if user set pin after prompted to by bot
                groupFlag = setGroupId(client, 'https://temptaking.ado.sg/group/{}'.format(client.groupId))
                if groupFlag == 0:
                    websiteStatus(True)
                    if not wstatus.status:
                        message(strings["status_offline_response"])
                        if not client.status.startswith("offline"):
                            client.status = "offline,{}".format(client.status)
                            client.put()
                    else:
                        msg = strings["website_error"]
                        markup = {
                            "keyboard": [
                                [
                                    strings["pin_keyboard"]
                                ]
                            ],
                            "one_time_keyboard": True
                        }
                        message(msg, markup)
                else:
                    # check that hasPin is now True
                    gm = json.loads(client.groupMembers)
                    try:
                        index = [obj["identifier"] for obj in gm].index(client.memberName)  # if this throws an
                        # exception, it means the user has changed their name and is probably trying to break the bot
                        client.memberId = gm[index]["id"]
                        client.memberName = gm[index]["identifier"]
                        client.pin = str(gm[index]["hasPin"])  # this should be true now

                        if client.pin == 'False':
                            msg = strings["set_pin_2"].format(client.groupId)
                            markup = {
                                "keyboard": [
                                    [
                                        strings["pin_keyboard"]
                                    ]
                                ],
                                "one_time_keyboard": True
                            }
                            message(msg, markup)
                            client.pin = 'no pin'
                        else:
                            message(strings["pin_msg_1"])
                            client.status = '5'
                        client.put()
                    except ValueError:
                        # user is probably trying to break the bot
                        message(strings["fatal_error"])
                        client.status = '1'
                        client.temp = 'init'
                        client.put()
                return response
            else:
                msg = strings["use_keyboard"]
                if client.pin == 'no pin':
                    markup = {
                        "keyboard": [
                            [
                                strings["pin_keyboard"]
                            ]
                        ],
                        "one_time_keyboard": True
                    }
                else:
                    markup = {
                        "keyboard": [
                            [
                                strings["member_keyboard_yes"]
                            ],
                            [
                                strings["member_keyboard_no"]
                            ]
                        ],
                        "one_time_keyboard": True
                    }
                message(msg, markup)
                return response

        elif client.status == '5':
            p = re.compile(r'\d{4}$').match(text)
            if p is None:
                reply(strings["invalid_pin"])
            else:
                msg = strings["pin_msg_2"].format(text)
                markup = {
                    "keyboard": [
                        [
                            strings["pin_keyboard_yes"]
                        ],
                        [
                            strings["pin_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = '6'
                client.pin = text
                client.put()
            return response

        elif client.status == '6':
            if text == strings["pin_keyboard_yes"]:
                msg = strings["setup_summary"].format(client.groupName, client.memberName, client.pin)
                markup = {
                    "keyboard": [
                        [
                            strings["summary_keyboard_yes"],
                            strings["summary_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = 'endgame 1'
                client.groupMembers = ''  # flush datastore
                client.put()
                return response
            elif text == strings["pin_keyboard_no"]:
                message(strings["pin_msg_3"])
                client.status = '5'
                client.put()
                return response
            else:
                msg = strings["use_keyboard"]
                markup = {
                    "keyboard": [
                        [
                            strings["pin_keyboard_yes"]
                        ],
                        [
                            strings["pin_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                return response

        elif client.status == 'endgame 1':
            now = datetime.now() + timedelta(hours=8)
            if text == strings["summary_keyboard_no"]:
                message(strings["SAF100"])
                client.status = '1'
                client.temp = 'init'
                client.put()
                return response
            # if the user doesn't enter summary_keyboard_no, we just assume they want to proceed
            if client.temp == 'init':
                if now.hour < 12:
                    message(strftime(now, strings["new_user_AM"]))
                else:
                    message(strftime(now, strings["new_user_PM"]))
                return response
            else:
                if now.hour < 12:
                    message((strftime(now,
                                      strings["already_submitted_AM"]).format(client.temp)
                             + strings["old_user_AM"]))
                else:
                    message((strftime(now,
                                      strings["already_submitted_PM"]).format(client.temp)
                             + strings["old_user_PM"]))
            return response

        elif client.status == 'endgame 2':
            p = re.compile(r'\d{2}[.]\d$').match(text)
            if p is None:
                temperatures = generateTemperatures()
                msg = strings["invalid_temp"]
                markup = {
                    "keyboard": temperatures,
                    "one_time_keyboard": True
                }
                message(msg, markup)
            else:
                temp = float(text)
                if temp >= 40.05 or temp <= 34.95:
                    temperatures = generateTemperatures()
                    msg = strings["temp_outside_range"]
                    markup = {
                        "keyboard": temperatures,
                        "one_time_keyboard": True
                    }
                    message(msg, markup)
                else:
                    resp = submitTemp(client, text)
                    if resp == 'OK':
                        client.temp = text
                        now = datetime.now() + timedelta(hours=8)
                        if now.hour < 12:
                            message((strftime(now,
                                              strings["just_submitted_AM"]).format(emojiTime(now), client.temp)
                                     + strings["old_user_AM"]))
                        else:
                            message((strftime(now,
                                              strings["just_submitted_PM"]).format(emojiTime(now), client.temp)
                                     + strings["old_user_PM"]))
                        client.status = 'endgame 1'
                        client.groupMembers = ''  # flush datastore
                        client.put()
                    elif resp == 'Wrong pin.':
                        message(strings["wrong_pin"])
                        client.status = 'wrong pin'
                        client.temp = 'error'
                        client.put()
                    else:
                        websiteStatus(True)
                        if not wstatus.status:
                            message(strings["status_offline_response"])
                            if not client.status.startswith("offline"):
                                client.status = "offline,{}".format(client.status)
                                client.put()
                        else:
                            message(strings["temp_submit_error"].format(client.groupId))
                            client.status = "endgame 1"
                            client.put()
                return response
        elif client.status == 'wrong pin':
            p = re.compile(r'\d{4}$').match(text)
            if p is None:
                reply(strings["invalid_pin"])
            else:
                msg = strings["pin_msg_2"].format(text)
                markup = {
                    "keyboard": [
                        [
                            strings["pin_resubmit_temp"]
                        ],
                        [
                            strings["pin_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = 'resubmit temp'
                client.pin = text
                client.put()
            return response
        elif client.status == 'resubmit temp':
            if text == strings["pin_resubmit_temp"]:
                temperatures = generateTemperatures()
                msg = strings["select_temp"]
                markup = {
                    "keyboard": temperatures,
                    "one_time_keyboard": True
                }
                message(msg, markup)
                client.status = 'endgame 2'
                client.put()
                return response
            elif text == strings["pin_keyboard_no"]:
                message(strings["pin_msg_3"])
                client.status = 'wrong pin'
                client.put()
                return response
            else:
                msg = strings["use_keyboard"]
                markup = {
                    "keyboard": [
                        [
                            strings["pin_resubmit_temp"]
                        ],
                        [
                            strings["pin_keyboard_no"]
                        ]
                    ],
                    "one_time_keyboard": True
                }
                message(msg, markup)
                return response
        else:
            reply(strings["invalid_input"])
        return response
