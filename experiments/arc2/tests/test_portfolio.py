import unittest

from arc2.portfolio import merge_predictions


def own(a,b,exact=True,cost=1):
    return {"attempts":[{"attempt_1":a,"attempt_2":b}],"diagnostics":{"selection":[[
        {"training_exact":exact,"cost":cost,"program":["test"]},
        {"training_exact":exact,"cost":cost+1,"program":["alternative"]}]]}}


class PortfolioTests(unittest.TestCase):
    def test_missing_cpp_preserves_python_predictions(self):
        x=own([[2]],[[3]])
        self.assertEqual(merge_predictions(x,{},3)[0],x["attempts"])

    def test_disagreement_uses_both_exact_engines(self):
        cpp={"predictions":[[[[4]],[[5]]]],"train_matches":[[3,3]],"scores":[[2.99,2.98]]}
        result,meta=merge_predictions(own([[2]],[[3]]),cpp,3)
        self.assertEqual(result,[{"attempt_1":[[2]],"attempt_2":[[4]]}])
        self.assertEqual([m["origin"] for m in meta[0]],["python","cpp"])

    def test_partial_cpp_never_displaces_second_exact_python(self):
        cpp={"predictions":[[[[4]]]],"train_matches":[[2]],"scores":[[99]]}
        result,_=merge_predictions(own([[2]],[[3]]),cpp,3)
        self.assertEqual(result,[{"attempt_1":[[2]],"attempt_2":[[3]]}])

    def test_duplicate_answers_do_not_consume_both_slots(self):
        cpp={"predictions":[[[[2]],[[4]]]],"train_matches":[[3,3]],"scores":[[2.99,2.98]]}
        result,_=merge_predictions(own([[2]],[[2]]),cpp,3)
        self.assertEqual(result,[{"attempt_1":[[2]],"attempt_2":[[4]]}])

    def test_invalid_cpp_grid_is_ignored(self):
        cpp={"predictions":[[[[11]]]],"train_matches":[[3]]}
        x=own([[2]],[[3]])
        self.assertEqual(merge_predictions(x,cpp,3)[0],x["attempts"])


if __name__=="__main__": unittest.main()
