"""Export a scientific plot of the frozen human-effort reference portfolio."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import models


def main():
    p=argparse.ArgumentParser();p.add_argument('--experiment',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();root=Path(args.experiment);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    export=json.loads((root/'portfolio-models.json').read_text())
    x=np.geomspace(1,2048,150);curves=[];weights=[]
    for cid,model in export['models'].items():
        curve=[models.conditional_progress(model['arc']['duration'],0,float(t),0,0)['probability_progress_within_budget'] for t in x]
        curves.append(curve);weights.append(export['weights'][cid])
    curves=np.array(curves);mean=np.asarray(weights)@curves
    fig,ax=plt.subplots(figsize=(10,5.4),layout='constrained')
    ax.fill_between(x,curves.min(axis=0),curves.max(axis=0),color='#c7d8ed',alpha=.65,label='Range across retained hypotheses (not a confidence interval)')
    for y in curves:ax.plot(x,y,color='#7890ac',alpha=.3,lw=.8)
    ax.plot(x,mean,color='#154c79',lw=2.8,label=f'Frozen equal-weight portfolio ({len(curves)} models)')
    ax.set_xscale('log',base=2);ax.set_xlim(1,2048);ax.set_ylim(0,1)
    ax.set_xlabel('Human actions until first level completion');ax.set_ylabel('Predicted cumulative probability')
    ax.set_title('Human effort reference: first level, button-only controls',loc='left',fontweight='bold')
    ax.grid(alpha=.18);ax.legend(loc='lower right',fontsize=8)
    fig.suptitle('ARC public human replays; models fitted on training environments, selected on validation environments',fontsize=9,color='#526171')
    for ext in ('png','svg'):fig.savefig(out/f'human-effort-forecast.{ext}',dpi=170)
    plt.close(fig)


if __name__=='__main__':main()
