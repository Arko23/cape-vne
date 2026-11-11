"""Run the maintained VNE simulator: python vne_simulation.py --help."""
import multiprocessing as mp
from vne.cli import main

if __name__ == '__main__':
    mp.freeze_support()
    main()
