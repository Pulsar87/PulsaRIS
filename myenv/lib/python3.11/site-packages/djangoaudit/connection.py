# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2010, 2degrees Limited <egoddard@tech.2degreesnetwork.com>.
# All Rights Reserved.
#
# This file is part of djangoaudit <https://launchpad.net/django-audit/>,
# which is subject to the provisions of the BSD at
# <http://dev.2degreesnetwork.com/p/2degrees-license.html>. A copy of the
# license should accompany this distribution. THIS SOFTWARE IS PROVIDED "AS IS"
# AND ANY AND ALL EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST
# INFRINGEMENT, AND FITNESS FOR A PARTICULAR PURPOSE.
#
##############################################################################

"""
All information relating to the connection to MongoDB
"""

from logging import getLogger

from django.conf import settings

from pymongo.connection import Connection
from pymongo.errors import ConnectionFailure, AutoReconnect, ConfigurationError

__all__ = ["MONGO_CONNECTION", "MongoConnectionError"]

_LOGGER = getLogger(__name__)

class MongoConnectionError(Exception):
    """
    If no connection to MongoDB can be established when a collection is
    retrieved this exception will be raised. All other connection operation will
    fail silently since the only operation which is ultimately important for
    django-audit is collection retrieval
    
    """
    
    pass

class MongoConnection(object):
    """A wrapper around PyMongo's connection to MongoDB"""
    
    def __init__(self, host, port):
        """
        Startup a connection to MongoDB on ``host`` and ``port``
        
        :param host: The host to connect to
        :type host: :class:`basestring`
        :param port: The port to connect on
        :type port: :class:`int`
        
        """
        self.host = host
        self.port = port
        
        self.connection = None
        self.connect()
        
        self._database = None
        
    def connect(self):
        """Make the connection to MongoDB."""
        
        try:
            self.connection = Connection(host=self.host, port=self.port)
            _LOGGER.debug('Successfully connection to MongoDB on %s:%d' %
                          (self.host, self.port))
        except AutoReconnect, exc:
            _LOGGER.warning("Got a reconnect exception when trying to connect "
                            "to MongoDB: %s", exc)
        except ConnectionFailure, exc:
            _LOGGER.critical("Could not establish a connection to MongoDB: %s",
                             exc)
        except ConfigurationError, exc:
            # pymongo doesn't differentiate between different types of
            # ConfigurationErrors. We are only interested in slave errors:
            if "must specify slave_okay to connect to slaves" in str(exc):
                _LOGGER.critical(exc)
            else:
                raise exc
    
    @property
    def database(self):
        """
        Retrieve the default database based on Django settings.
        
        Initially a lookup is performed and thereafter the cached database is
        returned.
        
        :rtype: :class:`pymongo.database.Database`
        
        """
        if not self._database:
            if not self.connection:
                # No connection has been established. We must have had an
                # earlier failure:
                self.connect()
                
                if not self.connection:
                    # If we're still not connected return None
                    return None
            
            database_name = settings.MONGO_DATABASE_NAME
            
            try:
                self._database = self.connection[database_name]
                _LOGGER.debug("Selected database %s for use", database_name)
            except AutoReconnect:
                _LOGGER.warn("Got an auto-reconnect message while selecting "
                             "database: %s", database_name)
            except ConnectionFailure, exc:
                _LOGGER.critical("Connection failure while trying to select "
                                 "database: %s", database_name)
            except ConfigurationError, exc:
                # pymongo doesn't differentiate between different types of
                # ConfigurationErrors. We are only interested in slave errors:
                if "must specify slave_okay to connect to slaves" in str(exc):
                    _LOGGER.critical(exc)
                else:
                    raise exc
        
        return self._database
    
    def get_collection(self, collection_name):
        """
        Get the collection specified by ``collection_name``
        
        :param collection_name: The name of the collection to use
        :type collection_name: :class:`basestring`
        :rtype: :class:`pymongo.collection.Collection`
        
        """
        if self.database is None:
            # The database cannot be retrieved due to connection issues. Log
            # this and raise an appropriate exception for capture later:
            message = ("Could not retrieve collection: %s, as no connection to "
                       "MongoDB was available." % collection_name)
            
            _LOGGER.critical(message)
            raise MongoConnectionError(message)
        
        return self.database[collection_name]
    
# Create the connection to MongoDB here:
MONGO_CONNECTION = MongoConnection(settings.MONGO_HOST, settings.MONGO_PORT)