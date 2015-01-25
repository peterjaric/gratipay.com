from faker import Factory
from gratipay import wireup, MAX_TIP_SINGULAR, MIN_TIP
from gratipay.elsewhere import PLATFORMS
from gratipay.models.participant import Participant
from gratipay.models import community
from gratipay.models import check_db
from psycopg2 import IntegrityError

import datetime
from decimal import Decimal as D
import random
import string


faker = Factory.create()


def _fake_thing(db, tablename, **kw):
    column_names = []
    column_value_placeholders = []
    column_values = []

    for k,v in kw.items():
        column_names.append(k)
        column_value_placeholders.append("%s")
        column_values.append(v)

    column_names = ", ".join(column_names)
    column_value_placeholders = ", ".join(column_value_placeholders)

    db.run( "INSERT INTO {} ({}) VALUES ({})"
            .format(tablename, column_names, column_value_placeholders)
          , column_values
           )
    return kw


def fake_text_id(size=6, chars=string.ascii_lowercase + string.digits):
    """Create a random text id.
    """
    return ''.join(random.choice(chars) for x in range(size))


def fake_sentence(start=1, stop=100):
    """Create a sentence of random length.
    """
    return faker.sentence(random.randrange(start,stop))


def fake_participant(db, number="singular", is_admin=False):
    """Create a fake User.
    """
    username = faker.first_name() + fake_text_id(3)
    try:
      _fake_thing( db
                 , "participants"
                 , username=username
                 , username_lower=username.lower()
                 , ctime=faker.date_time_this_year()
                 , is_admin=is_admin
                 , balance=0
                 , anonymous_giving=(random.randrange(5) == 0)
                 , anonymous_receiving=(number != 'plural' and random.randrange(5) == 0)
                 , balanced_customer_href=faker.uri()
                 , last_ach_result=''
                 , is_suspicious=False
                 , last_bill_result=''  # Needed to not be suspicious
                 , claimed_time=faker.date_time_this_year()
                 , number=number
                  )
    except IntegrityError:
      return fake_participant(db, number, is_admin)

    #Call participant constructor to perform other DB initialization
    return Participant.from_username(username)


def fake_community(db, creator):
    """Create a fake community
    """
    name = faker.city()
    if not community.name_pattern.match(name):
        return fake_community(db, creator)

    slug = community.slugize(name)

    creator.insert_into_communities(True, name, slug)

    return community.Community.from_slug(slug)


def fake_tip_amount():
    amount = ((D(random.random()) * (MAX_TIP_SINGULAR - MIN_TIP))
            + MIN_TIP)

    decimal_amount = D(amount).quantize(D('.01'))
    while decimal_amount == D('0.00'):
        # https://github.com/gratipay/gratipay.com/issues/2950
        decimal_amount = fake_tip_amount()
    return decimal_amount


def fake_tip(db, tipper, tippee):
    """Create a fake tip.
    """
    return _fake_thing( db
               , "tips"
               , ctime=faker.date_time_this_year()
               , mtime=faker.date_time_this_month()
               , tipper=tipper.username
               , tippee=tippee.username
               , amount=fake_tip_amount()
                )


def fake_elsewhere(db, participant, platform):
    """Create a fake elsewhere.
    """
    _fake_thing( db
               , "elsewhere"
               , platform=platform
               , user_id=fake_text_id()
               , user_name=participant.username
               , participant=participant.username
               , extra_info=None
                )


def fake_transfer(db, tipper, tippee):
        return _fake_thing( db
               , "transfers"
               , timestamp=faker.date_time_this_year()
               , tipper=tipper.username
               , tippee=tippee.username
               , amount=fake_tip_amount()
               , context='tip'
                )

def fake_exchange(db, participant, amount, fee, timestamp):
        return _fake_thing( db
               , "exchanges"
               , timestamp=timestamp
               , participant=participant.username
               , amount=amount
               , fee=fee
               , status='succeeded'
                )


def populate_db(db, num_participants=100, num_tips=200, num_teams=5, num_transfers=5000, num_communities=20):
    """Populate DB with fake data.
    """
    print("Making Participants")
    participants = []
    for i in xrange(num_participants):
        participants.append(fake_participant(db))

    print("Making Teams")
    for i in xrange(num_teams):
        t = fake_participant(db, number="plural")
        participants.append(t)
        #Add 1 to 3 members to the team
        members = random.sample(participants, random.randint(1, 3))
        for p in members:
            t.add_member(p)

    print("Making Elsewheres")
    for p in participants:
        #All participants get between 1 and 3 elsewheres
        num_elsewheres = random.randint(1, 3)
        for platform_name in random.sample(PLATFORMS, num_elsewheres):
            fake_elsewhere(db, p, platform_name)

    print("Making Communities")
    for i in xrange(num_communities):
        creator = random.sample(participants, 1)
        community = fake_community(db, creator[0])

        members = random.sample(participants, random.randint(1, 3))
        for p in members:
            p.insert_into_communities(True, community.name, community.slug)

    print("Making Tips")
    tips = []
    for i in xrange(num_tips):
        tipper, tippee = random.sample(participants, 2)
        tips.append(fake_tip(db, tipper, tippee))


    print("Making Transfers")
    transfers = []
    for i in xrange(num_transfers):
        tipper, tippee = random.sample(participants, 2)
        transfer = fake_transfer(db, tipper, tippee)
        transfers.append(transfer)

        db.run("""
          UPDATE participants
             SET balance = balance + %s
           WHERE username = %s
        """, (transfer['amount'], tippee.username))

        db.run("""
          UPDATE participants
             SET balance = balance - %s
           WHERE username = %s
        """, (transfer['amount'], tipper.username))

    print("Making Paydays")
    #First determine the boundaries - min and max date
    min_date = min(min(x['ctime'] for x in tips), \
                   min(x['timestamp'] for x in transfers))
    max_date = max(max(x['ctime'] for x in tips), \
                   max(x['timestamp'] for x in transfers))
    #iterate through min_date, max_date one week at a time
    date = min_date
    while date < max_date:
        end_date = date + datetime.timedelta(days=7)
        week_tips = filter(lambda x: date < x['ctime'] < end_date, tips)
        week_transfers = filter(lambda x: date < x['timestamp'] < end_date, transfers)
        week_participants = filter(lambda x: x.ctime.replace(tzinfo=None) < end_date, participants)
        credits = [] # Bank withdrawals
        debits = [] # Credit Card charges
        for p in week_participants:
          transfers_in = filter(lambda x: x['tippee'] == p.username, week_transfers)
          transfers_out = filter(lambda x: x['tipper'] == p.username, week_transfers)
          amount_in = sum([t['amount'] for t in transfers_in])
          amount_out = sum([t['amount'] for t in transfers_out])
          amount = amount_out - amount_in
          fee = amount * D('0.02')
          fee = abs(fee.quantize(D('.01')))
          if amount != 0:
            exchange = fake_exchange(
              db=db,
              participant=p,
              amount=amount,
              fee=fee,
              timestamp=(end_date - datetime.timedelta(seconds=1))
            )
            if amount > 0:
              debits.append(exchange)
              db.run("""
                UPDATE participants
                   SET balance = balance + %s
                 WHERE username = %s
              """, (amount, p.username))
            else:
              credits.append(exchange)
              db.run("""
                UPDATE participants
                   SET balance = balance + %s
                 WHERE username = %s
              """, (amount-fee, p.username))
        actives=set()
        tippers=set()
        for xfers in week_tips, week_transfers:
            actives.update(x['tipper'] for x in xfers)
            actives.update(x['tippee'] for x in xfers)
            tippers.update(x['tipper'] for x in xfers)
        payday = {
            'ts_start': date,
            'ts_end': end_date,
            'ntips': len(week_tips),
            'ntransfers': len(week_transfers),
            'nparticipants': len(week_participants),
            'ntippers': len(tippers),
            'nactive': len(actives),
            'transfer_volume': sum(x['amount'] for x in week_transfers)
        }
        payday['ach_volume'] = sum([e['amount'] for e in credits])
        payday['ach_fees_volume'] = sum([e['fee'] for e in credits])
        payday['charge_volume'] = sum([(e['amount'] + e['fee']) for e in debits])
        payday['charge_fees_volume'] = sum([e['fee'] for e in debits])
        _fake_thing(db, "paydays", **payday)
        date = end_date

def main():
    db = wireup.db(wireup.env())
    populate_db(db)
    check_db(db)


if __name__ == '__main__':
    main()
