import os
import sys
from traceback import print_exc
import socket
import time
import json
from re import findall, compile
import logging

import requests
from requests.exceptions import SSLError, ConnectionError
from dotenv import load_dotenv, set_key

load_dotenv()

logger = logging.getLogger(__name__)


class TwitchApi:
    """A class that contains all the methods that are required for interacting with the Twitch API. Also contains one method that uses the gql
    to read the links from a stream's panels
    """

    def __init__(self, *args, **kwargs):
        super(TwitchApi, self).__init__(*args, **kwargs)
        self.app_info = {
            "Client-ID": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("CLIENT_SECRET"),
            "token": self.get_token(),
        }
        self.headers = {
            "Client-ID": self.app_info["Client-ID"],
            "Authorization": f"Bearer {self.app_info['token']}",
        }

    def get_token(self):
        """Checks the stored token to make sure that it's still valid. Will request a new token if it's not valid.

        Returns:
            str: Twitch API access token
        """
        saved_token = os.getenv("ACCESS_TOKEN")
        # If there's a saved token, validate it
        if saved_token:
            r = requests.get("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {saved_token}"}).json()
            # Token is valid so return it
            if "client_id" in r:
                logger.info("Twitch API token verified")
                return saved_token

        # Use the client ID and client secret to request a token
        data = {
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("CLIENT_SECRET"),
            "grant_type": "client_credentials",
            "scope": "analytics:read:games",
        }
        r = requests.post("https://id.twitch.tv/oauth2/token", data=data).json()
        # Save the access token to the .env file and return it
        if "access_token" in r:
            logger.info("Saved new Twtich API token")
            set_key(".env", "ACCESS_TOKEN", r["access_token"])
            return r["access_token"]
        else:
            sys.exit("Unable to generate access token")

    def get_top_streams(self):
        """Gets the top channels with over 200 viewers

        Returns:
            list: a list of dictionaries containing information about the top channels
        """
        payload = {"game_id": (("id", "459931"), ("id", "2083"))}
        try:
            r = requests.get(
                "https://api.twitch.tv/helix/streams",
                headers=self.headers,
                params=payload,
                timeout=10,
            ).json()
            # Return streams with over 200 viewers
            return [s for s in r["data"] if s["viewer_count"] > 100]
        except (SSLError, ConnectionError, KeyError):
            return []

    def get_stream_details(self, streams: list):
        """Gets additional stream information from a list of streams

        Args:
            streams (list): list of streams to get additional information about

        Returns:
            dict: nested dictionary of user: { stream info }
        """
        logger.info(f"Loading extra info for {len(streams)} streams")
        stream_info = {
            s["user_name"].lower(): {
                "user_id": s["user_id"],
                "viewer_count": s["viewer_count"],
                "title": s["title"],
                "thumbnail": s["thumbnail_url"],
                "started": s["started_at"],
                "display": s["user_name"].lower()
            }
            for s in streams
        }

        payload = [("login", login) for login in stream_info]
        try:
            r = requests.get(
                "https://api.twitch.tv/helix/users",
                headers=self.headers,
                params=payload,
                timeout=10,
            ).json()
            for result in r["data"]:
                info = stream_info[result["login"]]
                info["broadcaster_type"] = result["broadcaster_type"]
                info["channel_views"] = result["view_count"]
                # If they're not partnered, get some extra channel info
                if info["broadcaster_type"] == "":
                    info["followers"] = self.get_follower_count(info["user_id"])
                    info["videos"] = self.get_video_count(info["user_id"])
        except:
            return {}
        return stream_info

    def get_video_count(self, user_id: str):
        """Get the number of VoDs that a channel has saved

        Args:
            user_id (str): user ID of the channel

        Returns:
            int: the number of videos that the channel has saved
        """
        payload = {"user_id": user_id}
        try:
            r = requests.get(
                "https://api.twitch.tv/helix/videos",
                headers=self.headers,
                params=payload,
                timeout=10,
            ).json()
            return len(r["data"])
        except:
            print_exc()
            # Return a high number so it doesn't trigger anything
            return 10000

    def get_follower_count(self, user_id: str):
        """Gets the number of users that are following a given channel

        Args:
            user_id (str): user ID of the channel

        Returns:
            int: number of users following the channel
        """
        payload = {"to_id": user_id}
        try:
            r = requests.get(
                "https://api.twitch.tv/helix/users/follows",
                headers=self.headers,
                params=payload,
                timeout=10,
            ).json()
            return r["total"]
        except:
            print_exc()
            # Return a high number so it doesn't trigger anything
            return 10000000

    @staticmethod
    def get_panel_links(user_id: str):
        """Gets any links that are contained in the panels underneath the video

        Args:
            user_id (str): user ID of the channel

        Returns:
            list: a list of unique URLs that were found in the panels
        """
        headers = {
            "Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36",
        }
        payload = json.dumps(
            [
                {
                    "operationName": "ChannelPanels",
                    "variables": {"id": user_id},
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": "236b0ec07489e5172ee1327d114172f27aceca206a1a8053106d60926a7f622e",
                        }
                    },
                }
            ]
        )
        try:
            r = requests.post(
                "https://gql.twitch.tv/gql", headers=headers, data=payload
            ).json()
        except:
            return []
            
        links = []
        for panel in r[0]["data"]["user"]["panels"]:
            if panel["linkURL"]:
                links.append(panel["linkURL"])
            if panel["description"]:
                url_regex = compile(
                    r"(?:https?:\/\/|(?:www\.))+[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
                )
                matches = findall(url_regex, panel["description"])
                if matches:
                    links += matches
        logger.warning(f"Found the following links in channel panels: {links}")
        return list(set(links))
