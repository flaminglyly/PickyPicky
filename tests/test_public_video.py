import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
from public_video import public_video

class PublicTests(unittest.TestCase):
    def setUp(self):
        self.page={'series_id':'123','vid':'456','publicVideoSeo':{'available':True,'seriesId':'123','itemId':'456','durationSeconds':200.552}}
        self.node={'@type':'VideoObject','url':'https://hongguoduanju.com/player/123','contentUrl':'https://hongguoduanju.com/video/public/456/test.mp4'}
    def extract(self):
        text='<script type="application/ld+json">'+json.dumps({'@graph':[self.node]})+'</script>'
        return public_video(text,self.page,'123','456')
    def test_valid_bound_public_resource(self):
        self.assertEqual(self.extract()['duration'],200.552)
    def test_recommended_video_rejected(self):
        self.node['contentUrl']='https://hongguoduanju.com/video/public/789/test.mp4'
        self.assertIsNone(self.extract())
    def test_seo_identity_required(self):
        self.page['publicVideoSeo']['itemId']='789'
        self.assertIsNone(self.extract())
    def test_no_public_permission(self):
        self.page['publicVideoSeo']['available']=False
        self.assertIsNone(self.extract())
    def test_external_and_credential_urls_rejected(self):
        for value in ['https://evil.test/video/public/456/a.mp4','https://user:pass@hongguoduanju.com/video/public/456/a.mp4']:
            self.node['contentUrl']=value
            self.assertIsNone(self.extract())
    def test_wrong_player_page_rejected(self):
        self.node['url']='https://hongguoduanju.com/player/999'
        self.assertIsNone(self.extract())

if __name__=='__main__':unittest.main()
