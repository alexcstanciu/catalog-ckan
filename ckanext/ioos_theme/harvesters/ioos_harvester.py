#!/usr/bin/env python
# -*- coding: utf-8 -*-
import ckan.plugins as p
import logging
from ckanext.spatial.harvesters.base import SpatialHarvester
from ckanext.spatial.interfaces import ISpatialHarvester
import json
from inflection import titleize
from collections import defaultdict

log = logging.getLogger(__name__)


class IOOSHarvester(SpatialHarvester):

    def get_package_dict(self, iso_values, harvest_object):
        '''
        '''
        package_dict = SpatialHarvester.get_package_dict(self, iso_values, harvest_object)
        simple_keys = {
            'publisher_info',
            'resource-provider',
            'distributor-info',
            'aggregation-info',
            'distributor-formats',
            'additional-information-source',
            'purpose',
            # Constraints
            'use-constraints',
            'access-constraints',
            'fees',
            # lineage
            'lineage',
            'lineage-process-steps',
        }
        extras = {k: iso_values.get(k) for k in simple_keys if k in iso_values}

        keywords = defaultdict(list)
        for keyword in iso_values['keywords']:
            keyword_type = keyword['type'] or 'keywords'
            keywords[keyword_type].append(keyword)

        extras['grouped_keywords'] = []
        for extra_name, matches in (('cf_standard_names',
                                     ('cf', 'climate and forecast')),
                                    ('gcmd_keywords',
                                     ('gcmd', 'global change'))):
            try:
                match_result = next((d['keywords'] for d in
                                     iso_values['keywords']
                                     if d['thesaurus'] and
                                     any(v in d['thesaurus']['title'].lower()
                                     for v in matches)), None)
            except:
                match_result = None
                log.exception("Execption raised when trying to extract {}".format(
                              extra_name))
            if match_result is not None:
                extras[extra_name] = match_result

        for keyword_type in ['theme', 'dataCenter', 'platform', 'instrument',
                             'place', 'project', 'dataResolution', 'stratum',
                             'otherRestrictions', 'keywords']:
            if keyword_type in keywords:
                extras['grouped_keywords'].append([titleize(keyword_type),
                                                   keywords[keyword_type]])

        if iso_values.get('publisher', None):
            extras['publisher'] = iso_values.get('publisher', [])
        if iso_values.get('browse-graphic', None):
            browse_graphic = iso_values['browse-graphic'][0]['file']
            extras['browse-graphic'] = browse_graphic
        if iso_values.get('dataset-edition'):
            extras['dataset-edition'] = iso_values['dataset-edition']
            package_dict["version"] = iso_values['dataset-edition'][0]
        if iso_values.get('presentation-form'):
            extras['presentation-form'] = iso_values['presentation-form'][0]
        if iso_values.get('responsible-organisation'):
            log.info("Checking for responsible-organisation")
            extras['responsible-organisation'] = iso_values.get('responsible-organisation', [])
        if iso_values.get('responsible-parties'):
            extras['responsible-parties'] = self.unique_responsible_parties(iso_values.get('responsible-organisation', []))

        for item in harvest_object.extras:
            key = item.key
            value = item.value
            if key == u'waf_location':
                extras['waf_location'] = value
                break
        else:
            extras['waf_location'] = None

        extras['object_reference'] = harvest_object.id

        extras_kv = [{'key': k,
                      'value': json.dumps(v) if isinstance(v, (list, dict))
                               else v} for k, v in extras.iteritems()]

        package_dict['extras'] = package_dict['extras'] + extras_kv
        package_dict['resources'] = self.filter_duplicate_resources(package_dict)
        package_dict['resources'] = self.reorder_resources(package_dict)
        package_dict = self.update_resources(package_dict)

        return package_dict

    def unique_responsible_parties(self, responsible_parties):
        '''
        Returns a modified list of responsible parties where only unique
        entries exist. Certain fields within the record are modified for cases
        when required tags are missing like names for URLs

        :param responsible_parties: List of CI_Responsible_Party parsed records
        '''
        rp_index = set()
        return_set = []
        for party in responsible_parties:
            try:
                contact_info = party.get('contact-info', {}) or {}
                online_resource = contact_info.get('online-resource', {}) or {}
                # Sometimes records will have empty contents for the online
                # resource, if that's the case just remove them or set the name
                # to Unspecified

                if 'name' in online_resource and online_resource['name'] == '':
                    if 'url' in online_resource and online_resource['url'] == '':
                        online_resource = {}
                    else:
                        online_resource['name'] = 'Online Resource'
                if 'url' in online_resource and not online_resource['url'].startswith('http'):
                    online_resource['url'] = 'http://' + online_resource['url']

                hash_key = ':'.join([
                    party['role'],
                    party.get('individual-name', ''),
                    party.get('organisation-name', ''),
                    contact_info.get('email', ''),
                    contact_info.get('phone', ''),
                    online_resource.get('url', ''),
                    online_resource.get('name', ''),
                    online_resource.get('protocol', ''),
                ])
                index_key = hash(hash_key)
                if index_key not in rp_index:
                    rp_index.add(index_key)
                    return_set.append(party)
            except Exception:
                continue

        return return_set

    def update_resources(self, package_dict):
        '''
        Returns the package dictionary with updated resources
        '''
        for resource in package_dict['resources']:
            # Skip resources that already have a format, but if you find "sos"
            # capitalize it. Also, change application/x-netcdf to netCDF
            if resource['format'] == 'sos':
                resource['format'] = 'SOS'
            elif resource['format'] == 'application/x-netcdf':
                resource['format'] = 'NetCDF'
            elif resource['format'] == 'application/x-msdos-program':
                resource['format'] = 'HTML'
            elif resource['format'] == 'erddap':
                resource['format'] = 'ERDDAP'
            elif resource['format'] == 'application/vnd.lotus-organizer':
                resource['format'] = 'HTML'

            if resource['resource_locator_protocol'] == 'WWW:LINK':
                resource['format'] = 'HTML'

            if resource['format'] == 'ERDDAP' and resource['resource_locator_protocol'] == 'OGC:WMS':
                resource['format'] = 'ERDDAP-WMS'

            if resource['name'] == 'OPeNDAP' and resource['description'] == 'THREDDS OPeNDAP':
                resource['format'] = 'OPeNDAP'

            if resource['resource_locator_protocol'] == 'OPeNDAP:OPeNDAP':
                if 'tabledap' in resource['url']:
                    resource['format'] = 'ERDDAP-TableDAP'
                elif 'erddap' in resource['url']:
                    resource['format'] = 'ERDDAP'
                else:
                    resource['format'] = 'OPeNDAP'

            if resource['resource_locator_protocol'] == 'ERDDAP:tabledap':
                resource['format'] = 'ERDDAP-TableDAP'
        return package_dict

    def filter_duplicate_resources(self, package_dict):
        '''
        Filters out duplicate resources based on name and URL
        '''

        found = []
        filtered = []
        for resource in package_dict['resources']:
            url = resource['url']
            name = resource['name']
            if (url, name) in found:
                continue
            found.append((url, name))
            filtered.append(resource)
        return filtered

    def reorder_resources(self, package_dict):
        '''
        Returns a list of resources in a prioritized order favoring OGC
        services before others.
        '''
        priority_services = [
            'opendap',
            'ogc-wcs',
            'ogc-wms',
            'ogc-sos',
            'ogc-wfs',
            'erddap',
        ]
        before = []
        after = []
        for resource in package_dict['resources']:
            if not resource['name']:
                after.append(resource)
            elif resource['name'].lower() in priority_services:
                before.append(resource)
            else:
                after.append(resource)

        return before + after

