// Adapted from Johan S. Wind's generic DSL runner, MIT license; see ../LICENSE
// and ../PROVENANCE.md. Historical task-specific/evaluation entry points are
// excluded. This runner never reads a test output or uses a task identifier.
#include "precompiled_stl.hpp"
using namespace std;
#include "utils.hpp"
#include "core_functions.hpp"
#include "image_functions.hpp"
#include "read.hpp"
#include "normalize.hpp"
#include "brute2.hpp"
#include "pieces.hpp"
#include "compose2.hpp"
#include "deduce_op.hpp"
#include "brute_size.hpp"

int MAXDEPTH = -1;
int MAXSIDE = 100, MAXAREA = 40*40, MAXPIXELS = 40*40*5;
int print_times = 0, print_mem = 0, print_nodes = 0;

static bool validAnswer(Image_ img) {
  if (img.w < 1 || img.w > 30 || img.h < 1 || img.h > 30) return false;
  if (img.mask.size() != img.w*img.h) return false;
  for (char c : img.mask) if (c < 0 || c > 9) return false;
  return true;
}

void run(int only_sid, int depth) {
  assert(depth >= 1 && depth <= 3);
  MAXDEPTH = depth*10;
  vector<Sample> samples = readAll("test", -1);
  assert(only_sid >= 0 && only_sid < samples.size());
  const Sample& s = samples[only_sid];
  Simplifier sim = normalizeCols(s.train);
  vector<pair<Image,Image>> train;
  for (auto& [in,out] : s.train) train.push_back(sim(in,out));
  // Only the test INPUT enters the search. No dummy output is required.
  Image test_in = sim.in(s.test_in);

  int maxarea = 1;
  for (auto& [in,out] : s.train)
    maxarea = max({maxarea, in.w*in.h, out.w*out.h});
  MAXAREA = maxarea*2;
  MAXPIXELS = MAXAREA*5;

  vector<point> out_sizes = bruteSize(test_in, train);
  vector<DAG> dags = brutePieces2(test_in, train, out_sizes);
  Pieces pieces = makePieces2(dags, train, out_sizes);
  for (DAG& d : pieces.dag) {
    d.hashi.clear();
    for (TinyNode& n : d.tiny_node.node) n.child.clear();
  }
  vector<Candidate> cands = composePieces2(pieces, train, out_sizes);
  addDeduceOuterProduct(pieces, train, cands);
  cands = evaluateCands(cands, train);
  sort(cands.begin(), cands.end());

  const string filename = "output/answer_"+to_string(only_sid)+"_"+to_string(depth)+".csv";
  FILE* fp = fopen(filename.c_str(), "w");
  assert(fp);
  fprintf(fp, "%s_%d\n", s.id.c_str(), s.id_ind);
  set<ull> seen;
  int emitted = 0;
  for (const Candidate& cand : cands) {
    Image answer = sim.rec(s.test_in, cand.imgs.back());
    if (!validAnswer(answer) || !seen.insert(hashImage(answer)).second) continue;
    // Export actual matches on ORIGINAL demonstrations, rather than infer them
    // from the upstream normalized-score-minus-complexity expression.
    int matches = 0;
    for (int i = 0; i < s.train.size(); i++) {
      Image reconstructed = sim.rec(s.train[i].first, cand.imgs[i]);
      if (reconstructed.sz == s.train[i].second.sz &&
          reconstructed.mask == s.train[i].second.mask) matches++;
    }
    fprintf(fp, "|");
    for (int r = 0; r < answer.h; r++) {
      for (int c = 0; c < answer.w; c++) fprintf(fp, "%d", answer(r,c));
      fprintf(fp, "|");
    }
    fprintf(fp, " %.20f %d\n", cand.score, matches);
    fflush(fp);
    if (++emitted >= 3) break;
  }
  fclose(fp);
}
