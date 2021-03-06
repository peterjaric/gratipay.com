from __future__ import unicode_literals

import json

from aspen.utils import utcnow
from gratipay.models.community import Community
from gratipay.testing import Harness

class TestCommunitiesJson(Harness):

    def test_post_name_pattern_none_returns_400(self):
        response = self.client.PxST('/for/communities.json', {'name': 'BadName!'})
        assert response.code == 400

    def test_post_is_member_not_bool_returns_400(self):
        response = self.client.PxST( '/for/communities.json'
                                   , {'name': 'Good Name', 'is_member': 'no'}
                                    )
        assert response.code == 400

    def test_joining_and_leaving_community(self):
        self.make_participant("alice", claimed_time=utcnow())

        response = self.client.GET('/for/communities.json', auth_as='alice')
        assert len(json.loads(response.body)['communities']) == 0

        response = self.client.POST( '/for/communities.json'
                                   , {'name': 'Test', 'is_member': 'true'}
                                   , auth_as='alice'
                                    )

        communities = json.loads(response.body)['communities']
        assert len(communities) == 1
        assert communities[0]['name'] == 'Test'
        assert communities[0]['nmembers'] == 1

        response = self.client.POST( '/for/communities.json'
                                   , {'name': 'Test', 'is_member': 'false'}
                                   , auth_as='alice'
                                    )

        response = self.client.GET('/for/communities.json', auth_as='alice')

        assert len(json.loads(response.body)['communities']) == 0

        # Check that the empty community was deleted
        community = Community.from_slug('test')
        assert not community

    def test_get_can_get_communities_for_user(self):
        self.make_participant("alice", claimed_time=utcnow())
        response = self.client.GET('/for/communities.json', auth_as='alice')
        assert len(json.loads(response.body)['communities']) == 0

    def test_get_can_get_communities_when_anon(self):
        response = self.client.GET('/for/communities.json')

        assert response.code == 200
        assert len(json.loads(response.body)['communities']) == 0
