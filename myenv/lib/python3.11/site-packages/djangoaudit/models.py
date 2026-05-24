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

from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal
from logging import getLogger


from django.db.models.base import ModelBase, Model
from django.db.models.fields import DecimalField


from djangoaudit.connection import *


__all__ = ["AuditedModel"] 

    
_LOGGER = getLogger(__name__)

AUDITING_COLLECTION_NAME = 'audit_data'
"""The name of the collection to use for auditing"""

class _collection_handler(object):
    """
    Lazy way of accessing the collection which handles intermittent failures in
    the connection
    """
    
    def __init__(self, collection_name):
        """
        
        :param collection_name: The name of the collection to use
        :type collection_name: :class:`basestring`
        
        """
        
        self.collection_name = collection_name
        self.collection = None
        
    def _get_collection(self):
        """Actually get the connection and handle failure to acquire it"""
        try:
            self.collection = MONGO_CONNECTION.get_collection(self.collection_name)
        except MongoConnectionError:
            self.collection = None
            raise
        
    def __call__(self):
        """
        Return either the collection or allow the MongoConnectionError to
        propagate to the calling code
        
        :return: The collection (if available)
        :rtype: :class:`pymongo.collection.Collection`
        
        """
        
        if not self.collection:
            self._get_collection()
            
        return self.collection
            
AUDITING_COLLECTION = _collection_handler(AUDITING_COLLECTION_NAME)    
"""The collection to use for Auditing"""    
          

def _get_params_from_model(model):
    """
    Return a dictionary containing object_app, object_model, object_pk
    corresponding to ``model``
    
    object_app is the Django app containing the model
    object_model is the Django model itself
    object_pk is the primary key of ``model``
    
    :param model: A Django model
    :type model: :class:`django.db.models.base.Model`
    :rtype: dict
    
    """
    
    return dict(object_app=model._meta.app_label,
                object_model=model._meta.object_name,
                object_pk=model.pk)
    

def _coerce_to_bson_compatible(value):
    """
    Ensure that any types which cannot be encoded into BSON are converted
    appropriately
    
    BSON cannot handle the following:
    * dates - convert to datetime
    * decimals - convert to float
    """
    
    if isinstance(value, Decimal):
        # Convert to float:
        return float(value)
    elif isinstance(value, date) and not isinstance(value, datetime):
        return datetime.fromordinal(value.toordinal())
    
    return value

def _coerce_datum_to_model_types(model_class_or_inst, field, value):
    """
    Decide whether to coerce a particular field's value or not.
    
    :param model_class_or_inst: The class or instance of AuditedModel
    :type model_class_or_inst: :class:`AuditedModel`
    :param field: The field to test for coercion
    :type field: :class:'basestring`
    :param value: The value to coerce
    
    """
    
    
    if field in model_class_or_inst.log_fields:
        field_inst = model_class_or_inst._meta.get_field_by_name(field)[0]
        
        # Due to the inability of Decimal to directly convert floats and
        # DecimalField's oversight for this fact, convert to a string
        # first:
        if isinstance(field_inst, DecimalField):
            # Make the string formatter:
            formatter = "%%%d.%df" % (field_inst.max_digits,
                                      field_inst.decimal_places)
            value = formatter % value
        return field_inst.to_python(value)
    return value


def _coerce_data_to_model_types(model_class_or_inst, data):
    """
    Coerce values in ``data`` to the types specified on ``model_class_or_inst``
    
    :param model_class_or_inst: The class or instance of AuditedModel
    :type model_class_or_inst: :class:`AuditedModel`
    :param data: The MongoDB record for analysis
    :type data: BSON dict
    
    """
    
    coerced_data = {}
    for key, value in data.items():
        coerced_data[key] = _coerce_datum_to_model_types(model_class_or_inst,
                                                         key,
                                                         value)
            
    return coerced_data


def _audit_model(model, initial_values, final_values, operator=None, notes=None,
                 **extra_info):
    """
    Calculate the differences on a model as an adjunct for AuditedModel 
    
    :param model: The Django model this change relates to
    :param initial_values: A :class:`dict` of initial values
    :param final_values: A :class:`dict` of final values
    :param operator: Optional operator who made the change
    :param notes: Optional notes to be recorded against this change
    
    """
    
    # make the object key for this model:
    audit = _get_params_from_model(model)
    audit['audit_date_stamp'] = datetime.utcnow()
    
    # append any optional data:
    if operator:
        audit['audit_operator'] = operator
        
    if notes:
        audit['audit_notes'] = notes
    
    changes = False
    for key, final_value in final_values.iteritems():
        initial_value = initial_values.get(key)
        # TODO: Can this be simplified? Seems to break the tests by doing so
        if initial_value is None and final_value is not None:
            audit[key] = _coerce_to_bson_compatible(final_value)
            changes = True
        else:
            if initial_value != final_value:
                audit[key] = _coerce_to_bson_compatible(final_value)
                changes = True
    
    if extra_info:
        for key, value in extra_info.iteritems():
            audit[key] = _coerce_to_bson_compatible(value)
            changes = True
    
    if not changes:
        # No point in writing this to to DB:
        return None
    
    # Write out the document and return it's DB id:
    try:
        return AUDITING_COLLECTION().insert(audit)
    except MongoConnectionError, exc:
        _LOGGER.critical("Error while writing document to collection: %s "
                         "Audit data: %r.",  exc, audit)
        return None


class AuditedModelMeta(ModelBase):
    """ Meta class for :class:`AuditedModel` """
    
    def __new__(cls, name, bases, attrs):
        if not "log_fields" in attrs:
            attrs["log_fields"] = []
        
        new_class = super(AuditedModelMeta, cls).__new__(cls, name, bases, attrs)
        
        log_fields = new_class.log_fields
        
        if log_fields:
            # Raise an exception if we're trying to log a field which doesn't
            # exist on the model:
            defined_fields = [f.name for f in new_class._meta.fields]
            
            for field in log_fields:
                if field not in defined_fields:
                    raise AttributeError("Cannot log data for %r as it does not"
                                         " exist on the model" % field)
        
        return new_class
        
class AuditedModel(Model):
    """
    A version of django.db.models.Model that will audit any values specified in 
    the log_fields class attribute
    
    """
    
    __metaclass__ = AuditedModelMeta
    
    class Meta:
        abstract = True
    
    def __init__(self, *args, **kwargs):
        super(AuditedModel, self).__init__(*args, **kwargs)
        
        # Ensure that we can store any extra auditing information on the instance:
        self._audit_info = defaultdict(lambda: None)
    
    def save(self, *args, **kwargs):
        """
        The save method performs auditing on the model to record the differences
        before and after the commit to the DB.
        
        """
        
        # Before we save to the DB, get the values from the original instance:
        empty_values = False
        
        if self.pk is None:
            # This is the first save, the record is being created:
            empty_values = True
        else:
            try:
                init_values = self.__class__.objects.filter(pk=self.pk)\
                                            .values(*self.log_fields)[0]
            except IndexError:
                empty_values = True
                
        if empty_values:
            # we don't know what the initial state is, so assume None:
            init_values = {}
            
            for field in self.log_fields:
                init_values[field] = None
                
        final_values = {}
        
        for field in self.log_fields:
            # We can't just get the attribute directly off the instance here
            # because we need to ensure it is of the same type as the initial
            # value. To do this we use the field's `to_python` method:
            field_inst = self._meta.get_field_by_name(field)[0]
            
            final_values[field] = field_inst.to_python(field_inst
                                                       .value_from_object(self))
        
        # need to actually save the model here to ensure pk for the auditing
        super(AuditedModel, self).save(*args, **kwargs)
            
        _audit_model(self, init_values, final_values, 
                    **self._audit_info)
        
    def delete(self, *args, **kwargs):
        """
        The delete method performs auditing on the model to record the state of 
        the model prior to deletion.
        
        """
        
        initial_values, final_values = {}, dict(audit_is_delete=True)
        
        for field in self.log_fields:
            final_values[field] = getattr(self, field)
        
        delete_note = "Object deleted. These are the attributes at delete time."
        
        # log that this object is being deleted and cater for the case where
        # other notes have been specified:
        notes = self._audit_info['notes']
        
        if notes is None:
            notes = delete_note
        else:
            notes = "%s\n%s" % (delete_note, notes)
            
        _audit_model(self, initial_values, final_values,
                    self._audit_info['operator'], notes)
        
        super(AuditedModel, self).delete(*args, **kwargs)
    
    def set_audit_info(self, **kwargs):
        """Set extra audit information on this instance."""
        
        self._audit_info.update(kwargs)
    
    def get_audit_log(self):
        """
        Construct a generator of all the items in the audit log for this object.
        
        All data in the object will be converted into the correct type. Each log
        entry is returned a dictionary of directly set data with an additional 
        key called ``audit_changes``. This value is a dictionary of the fields
        which have changed on the model. e.g.::
        
            {'operator' : 'power_user',
             'extra': 'Extra info',
             'audit_changes': {'seats': (10, 20),
                               'premium': (False, True)
                              }
            }
        
        """
        
        # First get a list of fields on the model we actually want to diff:
        diff_fields = frozenset(self.log_fields)
        
        # Now set up a defaultdict with None for all these fields initial values:
        previous_fields = defaultdict(lambda: None)
    
        for datum in AUDITING_COLLECTION().find(_get_params_from_model(self)):
            entry = {}
            changes = {}
            for field, value in datum.iteritems():
                # If the field is a log field report the diff:
                if field in diff_fields:
                    new_value = _coerce_datum_to_model_types(self, field, value)
                    # Record the delta:
                    changes[field] = (previous_fields[field], new_value)
                    
                    # Now update the previous_fields record:
                    previous_fields[field] = new_value
                else:
                    # Just record this directly as an entry in the log:
                    entry[field] = value
            
            # Now put the log together (combine the direct log and changes):
            if changes:
                entry['audit_changes'] = changes 
            yield entry
            
    def get_creation_log(self):
        """
        Get the values logged on the creation of this instance or None if not
        available
        
        :return: The document from MongoDB associated with the creation of this
            record
        :rtype: :class:`dict`
        
        """
        try:
            data = AUDITING_COLLECTION().find(_get_params_from_model(self))\
                                        .sort('audit_date_stamp')[0]
        except IndexError:
            return None
        
        return _coerce_data_to_model_types(self, data)
        
    
    @classmethod
    def get_deleted_log(cls, pk=None):
        """
        Construct a generator of all items which have been deleted for this model.
        If ``pk`` is specified, then the results will be filtered for that
        primary key.
        
        :param pk: The primary key of the instance to consider (optional)
        
        """
        
        query = dict(audit_is_delete=True, object_app=cls._meta.app_label,
                     object_model=cls._meta.object_name)
        
        if pk:
            query['object_pk'] = pk
        
        for datum in AUDITING_COLLECTION().find(query):
            yield _coerce_data_to_model_types(cls, datum)