# -*- coding: utf-8 -*-
import logging

from pyramid.settings import asbool

from .base import View, CreateView, EditView, DeleteView

from pyvac.models import User, Group
from pyvac.helpers.i18n import trans as _
from pyvac.helpers.ldap import LdapCache, hashPassword, randomstring


log = logging.getLogger(__name__)


class MandatoryLdapPassword(Exception):
    """ Raise when no password has been provided when creating a user """


class List(View):
    """
    List all user accounts
    """
    def render(self):

        return {u'user_count': User.find(self.session, count=True),
                u'users': User.find(self.session),
                }


class AccountMixin:
    model = User
    matchdict_key = 'user_id'
    redirect_route = 'list_account'

    def update_view(self, model, view):
        settings = self.request.registry.settings
        ldap = False
        if 'pyvac.use_ldap' in settings:
            ldap = asbool(settings.get('pyvac.use_ldap'))

        view['groups'] = Group.all(self.session, order_by=Group.name)
        view['managers'] = User.by_role(self.session, 'manager')
        if ldap:
            ldap = LdapCache()
            view['managers'] = ldap.list_manager()
            view['units'] = ldap.list_ou()
            view['countries'] = User.choose_country
            # generate a random password for the user, he will change it later
            password = randomstring()
            log.info('temporary password generated: %s' % password)
            view['password'] = password
            view['view_name'] = self.__class__.__name__.lower()
            view['myself'] = (self.user.id == self.get_model().id)

    def append_groups(self, account):
        exists = []
        group_ids = [int(id) for id in self.request.params.getall('groups')]

        if not group_ids:
            group_ids = [Group.by_name(self.session, u'user').id]

        # only update if there is at least one group provided
        if group_ids:
            for group in account.groups:
                exists.append(group.id)
                if group.id not in group_ids:
                    account.groups.remove(group)

            for group_id in group_ids:
                if group_id not in exists:
                    account.groups.append(Group.by_id(self.session, group_id))


class Create(AccountMixin, CreateView):
    """
    Create account
    """

    def save_model(self, account):
        super(Create, self).save_model(account)
        self.append_groups(account)

        if account.ldap_user:
            # create in ldap
            r = self.request
            ldap = LdapCache()
            if 'ldappassword' not in r.params:
                raise MandatoryLdapPassword()
            new_dn = ldap.add_user(account, password=r.params['ldappassword'],
                                   unit=r.params['unit'])
            # update dn
            account.dn = new_dn

        if self.user and not self.user.is_admin:
            self.redirect_route = 'list_request'

    def validate(self, model, errors):
        r = self.request
        if 'user.password' in r.params:
            if r.params['user.password'] != r.params['confirm_password']:
                errors.append(_('passwords do not match'))
        return len(errors) == 0


class Edit(AccountMixin, EditView):
    """
    Edit account
    """

    def save_model(self, account):
        super(Edit, self).update_model(account)
        self.append_groups(account)

        if account.ldap_user:
            # update in ldap
            r = self.request
            if 'user.password' in r.params and r.params['user.password']:
                password = [hashPassword(str(r.params['user.password']))]

            ldap = LdapCache()
            ldap.update_user(account, password)

        if self.user and not self.user.is_admin:
            self.redirect_route = 'list_request'

    def validate(self, model, errors):
        r = self.request
        settings = r.registry.settings
        ldap = False
        if 'pyvac.use_ldap' in settings:
            ldap = asbool(settings.get('pyvac.use_ldap'))

        if 'current_password' in r.params and r.params['current_password']:
            if not User.by_credentials(self.session, model.login,
                                       r.params['current_password'], ldap):
                errors.append(_(u'current password is not correct'))
            elif r.params['user.password'] == r.params['current_password']:
                errors.append(_(u'password is inchanged'))

            if r.params['user.password'] != r.params['confirm_password']:
                errors.append(_(u'passwords do not match'))

            if errors:
                self.request.session.flash('error;%s' % ','.join(errors))

        return len(errors) == 0


class Delete(AccountMixin, DeleteView):
    """
    Delete account
    """

    def delete(self, account):
        super(Delete, self).delete(account)
        if account.ldap_user:
            # delete in ldap
            ldap = LdapCache()
            ldap.delete_user(account.dn)
