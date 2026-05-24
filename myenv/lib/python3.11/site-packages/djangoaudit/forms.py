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
A module to store a version of django.forms.ModelForm to work with
djangoaudit.models.AuditedModel

"""

from django.forms import ModelForm

__all__ = ['AuditedModelForm']

class AuditedModelForm(ModelForm):
    """
    A version of django.forms.ModelForm to allow operator and notes to be
    specified to work with djangoaudit.models.AuditedModel
    
    """
    
    def save(self, commit=True, operator=None, notes=None):
        """
        Save the data in the form to the audited model instance.
        
        :param commit: Whether to commit (see django docs for more info)
        :type commit: :class:`bool`
        :param operator: Optional operator to record against this save
        :param notes: Optional notes to record against this save
        
        """
        
        if not hasattr(self.instance, '_audit_info'):
            raise AttributeError("Cannot save this form as the model instance "
                                 "does not have the attribute  '_audit_info'")
        
        self.instance.set_audit_info(operator=operator, notes=notes)
        
        super(AuditedModelForm, self).save(commit=commit)