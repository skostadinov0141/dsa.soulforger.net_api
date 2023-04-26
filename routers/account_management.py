from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Response
from models.account_management.account import Account
from pymongo import MongoClient
from bson.objectid import ObjectId
from urllib.parse import quote_plus 
from dotenv import load_dotenv
from validators.account_management import validate_pw, validate_email
from pprint import pprint
import datetime
import bson
import yaml
import uuid
import os
import bcrypt
import re



# region Database

load_dotenv('dsa_soulforger.env')

uri = "mongodb://%s:%s@%s/?authSource=%s" % (
    quote_plus(os.environ.get('DSA_SOULFORGER_DB_ACCOUNTMANAGER_UNAME')), 
    quote_plus(os.environ.get('DSA_SOULFORGER_DB_ACCOUNTMANAGER_PASS')), 
    f"{os.environ.get('DSA_SOULFORGER_DB_IP')}:{os.environ.get('DSA_SOULFORGER_DB_PORT')}",
    quote_plus(os.environ.get('DSA_SOULFORGER_DB_ACCOUNTMANAGER_SOURCE')),
)

mongo = MongoClient(uri, serverSelectionTimeoutMS=5)

database = mongo['dsa_soulforger_net']
# endregion



# region Router
router = APIRouter(
    prefix='/auth',
    tags=['Authentication']
)
# endregion



# region API Methods

def authenticate(request: Request) -> Optional[dict]:
    session_id = request.state.session_id
    session = database.sessions.find_one({'session_id':session_id})
    if session:
        return {
            'session_id':session_id,
            'user_id': session['user_id'],
            'session_oid': session['_id']
        }
    else:
        raise HTTPException(status_code=401, detail='Not Authorized!')


@router.get('/user')
async def get_user_data( response: Response, auth: dict = Depends(authenticate)):
    db_result = database['users'].find_one({'_id':auth['user_id']})
    del db_result['_id']
    del db_result['password_hash']
    return db_result


@router.post('/register')
async def register_account(acc: Account):
    print('here')
    # Validate email and password, store the results in a list of dicts
    validations = [
        validate_email(acc.email, database),
        validate_pw(acc.password)
    ]
    # iterate over the validation dicts and if any validation is false return a 400 Bad Request
    # additionally make sure that the eula has been accepted
    final_result = True
    final_details = []
    for i in validations:
        if i['result'] == False:
            final_result = False
        for d in i['details']:
            final_details.append(d)
    if acc.eula == False:
        final_result = False
        final_details.append({
            'category':'eula',
            'detail':'NONE'
        })
    if acc.password != acc.password_confirmation:
        final_result = False
        final_details.append({
            'category':'password_confirmation',
            'detail':'Die Passwörter stimmen nicht überein.'
        })
    if acc.display_name == '':
        final_result = False
        final_details.append({
            'category':'display_name',
            'detail':'Der Anzeigename darf nicht leer sein.'
        })
    if final_result == False:
        raise HTTPException(400,final_details)
    # Hash pw and create an account in the DB if all inputs are valid
    hashedPWD = bcrypt.hashpw(acc.password.encode(), bcrypt.gensalt(rounds=14))
    userProfile = {
        'email':acc.email,
        'password_hash':hashedPWD.decode(),
        'display_name':acc.display_name
    }
    # insert into database
    database['users'].insert_one(userProfile)
    return {'result' : True}


@router.post("/login")
async def login(email: str, password: str, request: Request, keep_logged_in: bool):
    # Get user from DB and create a session object to save to the DB
    user = database.users.find_one({'email':email})
    existing_session = database.sessions.find_one({'session_id': request.state.session_id})
    # Check if a session already exists, if it does return true
    if existing_session:
        user_obj = database.users.find_one({'_id':existing_session['user_id']},{'_id':False,'email':False,'password_hash':False})
        user_obj['expires_at'] = existing_session["expires_at"]
        return user_obj
    if user and bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        session_id = request.state.session_id
        session_obj = {
            "session_id": session_id, 
            "user_id": user["_id"],
        }
        # If keep_logged_in is false include a ttl field to the session object
        if keep_logged_in == False:
            session_obj["expires_at"] = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=6)
        # Insert into DB
        database.sessions.insert_one(session_obj)
        user_obj = database.users.find_one({'_id':user["_id"]},{'_id':False,'email':False,'password_hash':False})
        user_obj['expires_at'] = session_obj["expires_at"]
        return user_obj
    else:
        raise HTTPException(status_code=401, detail="Passwort und E-Mail stimmen nicht überein.")
    

@router.get("/verify-session")
async def verify_session(request: Request):
    session_id = request.state.session_id
    session = database.sessions.find_one({'session_id':session_id})
    if session:
        return {'result':True}
    else:
        return {'result':False}

        
# endregion