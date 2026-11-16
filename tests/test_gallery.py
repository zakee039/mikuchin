"""Gallery regression tests: never touch the user's chat directory."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT / "backend" / "polystrata"))
from serve import gallery
from serve.session_v1 import SessionV1


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = SessionV1(self.tmp.name)
        self.svc = SimpleNamespace(session_v1=self.session)
        self.one = "a" * 32
        self.two = "b" * 32
        self.three = "c" * 32

    def write_image(self, ident, size=(48,64)):
        path = self.session.generated_dir / (ident+".png")
        Image.new("RGB",size,(15,180,130)).save(path,"PNG")
        return path

    def test_backfill_recovers_chat_source_without_touching_other_assets(self):
        self.write_image(self.one)
        self.write_image(self.two)
        other = self.session.images_dir / "user-provided.png"
        Image.new("RGB",(8,8)).save(other,"PNG")
        messages = [{"role":"assistant","tools":[{
            "name":"polystrata__generate_image","image_file":self.one+".png",
            "image_model":"qwen-image-turbo-uncensored","image_prompt":"a picture"
        }]}]
        with self.session.lock, self.session._db() as c:
            self.session._ensure(c,"chat-1")
            c.execute("UPDATE conversations SET web_messages=? WHERE id=?",
                      (json.dumps(messages),"chat-1"))
        result = gallery.listing(self.svc)
        self.assertEqual(result["total"],2)
        lookup={x["id"]:x for x in result["items"]}
        self.assertEqual(lookup[self.one]["source"],"chat")
        self.assertEqual(lookup[self.one]["session_id"],"chat-1")
        self.assertEqual(lookup[self.one]["prompt"],"a picture")
        self.assertTrue(lookup[self.one]["nsfw"])
        self.assertEqual(lookup[self.two]["source"],"studio")
        self.assertEqual(lookup[self.two]["width"],48)
        self.assertTrue(other.is_file())

    def test_write_preserves_manual_nsfw_and_chat_source(self):
        self.write_image(self.one)
        gallery.register(self.svc,self.one+".png",model="uncensored-model",provider="local")
        self.assertTrue(gallery.listing(self.svc)["items"][0]["nsfw"])
        gallery.set_nsfw(self.svc,self.one,False)
        gallery.register(self.svc,self.one+".png",source="chat",
                         model="uncensored-model",provider="api",session_id="chat-x")
        result=gallery.listing(self.svc)["items"][0]
        self.assertFalse(result["nsfw"])
        self.assertEqual(result["source"],"chat")
        self.assertEqual(result["provider"],"api")

    def test_thumbnail_and_safe_batch_deletion(self):
        self.write_image(self.one)
        self.write_image(self.two)
        gallery.listing(self.svc)
        jpeg=gallery.thumbnail(self.svc,self.one)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        thumb_dir=self.session.root/"gallery-thumbnails"
        self.assertTrue((thumb_dir/(self.one+".jpg")).is_file())
        unrelated=self.session.root/"do-not-delete.txt"
        unrelated.write_text("private")
        self.assertRaises(gallery.GalleryError,gallery.delete_many,self.svc,["../do-not-delete"])
        result=gallery.delete_many(self.svc,[self.one,self.two,self.two])
        self.assertEqual(len(result["deleted"]),2)
        self.assertFalse((self.session.generated_dir/(self.one+".png")).exists())
        self.assertTrue(unrelated.is_file())
        self.assertIsNone(gallery.thumbnail(self.svc,self.one))
        self.assertEqual(gallery.listing(self.svc)["total"],0)

    def test_missing_file_reconciled_and_external_repair(self):
        gallery.listing(self.svc)
        p=self.write_image(self.one)
        self.assertEqual(gallery.listing(self.svc)["total"],0)
        self.assertEqual(gallery.repair(self.svc)["added"],1)
        self.assertEqual(gallery.listing(self.svc)["total"],1)
        p.unlink()
        self.assertEqual(gallery.listing(self.svc)["total"],0)

    def test_filters_sort_and_mark(self):
        self.write_image(self.one)
        self.write_image(self.two)
        gallery.register(self.svc,self.one,source="studio",provider="local")
        gallery.register(self.svc,self.two,source="chat",provider="api",session_id="chat-x")
        self.assertEqual(gallery.listing(self.svc,source="studio")["total"],1)
        self.assertEqual(gallery.listing(self.svc,source="api")["total"],1)
        self.assertEqual(gallery.listing(self.svc,source="chat")["total"],1)
        self.assertEqual(gallery.listing(self.svc,limit=1,offset=1)["items"].__len__(),1)
        self.assertTrue(gallery.set_nsfw(self.svc,self.two,True)["nsfw"])
        self.assertTrue(next(x for x in gallery.listing(self.svc)["items"]
                             if x["id"]==self.two)["nsfw"])
        with self.assertRaises(gallery.GalleryError):
            gallery.set_nsfw(self.svc,self.one,"true")
        with self.assertRaises(gallery.GalleryError):
            gallery.listing(self.svc,source="no")

    def setup_pair(self):
        self.write_image(self.one,(192,192))
        self.write_image(self.two,(48,48))
        gallery.register(self.svc,self.one,source="chat",provider="local",model="demo-upscaled")
        gallery.register(self.svc,self.two,source="chat",provider="local",
                         model="demo-original",parent_id=self.one)

    def test_grouped_pairs_and_batch_nsfw(self):
        self.setup_pair()
        result=gallery.listing(self.svc)
        self.assertEqual(result["total"],1)
        entry=result["items"][0]
        self.assertEqual(entry["id"],self.one)
        self.assertEqual(entry["variant_count"],2)
        self.assertEqual(entry["variants"],{"original":self.two,"upscaled":self.one})
        self.assertEqual(gallery.listing(self.svc,source="chat")["total"],1)
        self.assertEqual(gallery.listing(self.svc,source="local")["total"],1)
        changed=gallery.set_nsfw_many(self.svc,[self.one],True)
        self.assertEqual(changed["updated"],[self.one])
        with gallery._db(self.svc) as c:
            values=c.execute("SELECT nsfw FROM images WHERE id IN (?,?)",
                             (self.one,self.two)).fetchall()
        self.assertEqual([row[0] for row in values],[1,1])
        self.assertTrue(gallery.listing(self.svc)["items"][0]["nsfw"])
        gallery.set_nsfw(self.svc,self.two,False)
        self.assertFalse(gallery.listing(self.svc)["items"][0]["nsfw"])
        with self.assertRaises(gallery.GalleryError):
            gallery.set_nsfw_many(self.svc,[self.one,"g"*32],True)

    def test_group_default_delete_removes_both_files(self):
        self.setup_pair()
        result=gallery.delete_many(self.svc,[self.one])
        self.assertEqual(result["deleted_groups"],1)
        self.assertEqual(set(result["deleted"]),{self.one,self.two})
        self.assertEqual(gallery.listing(self.svc)["total"],0)
        self.assertFalse((self.session.generated_dir/(self.one+".png")).exists())
        self.assertFalse((self.session.generated_dir/(self.two+".png")).exists())

    def test_delete_original_retains_4x(self):
        self.setup_pair()
        result=gallery.delete_variant(self.svc,self.one,"original")
        self.assertEqual(result["deleted"],[self.two])
        self.assertEqual(result["remaining"],self.one)
        view=gallery.listing(self.svc)
        self.assertEqual(view["total"],1)
        self.assertEqual(view["items"][0]["variant_count"],1)
        self.assertTrue((self.session.generated_dir/(self.one+".png")).exists())
        self.assertFalse((self.session.generated_dir/(self.two+".png")).exists())
        with self.assertRaises(gallery.GalleryError):
            gallery.delete_variant(self.svc,self.one,"original")

    def test_delete_upscaled_promotes_original(self):
        self.setup_pair()
        gallery.set_nsfw(self.svc,self.one,True)
        result=gallery.delete_variant(self.svc,self.one,"upscaled")
        self.assertEqual(result["deleted"],[self.one])
        self.assertEqual(result["remaining"],self.two)
        view=gallery.listing(self.svc)
        self.assertEqual(view["total"],1)
        self.assertEqual(view["items"][0]["id"],self.two)
        self.assertEqual(view["items"][0]["variant_count"],1)
        self.assertEqual(view["items"][0]["width"],48)
        self.assertTrue(view["items"][0]["nsfw"])
        self.assertTrue((self.session.generated_dir/(self.two+".png")).is_file())
        self.assertFalse((self.session.generated_dir/(self.one+".png")).exists())

if __name__=="__main__":
    unittest.main()
