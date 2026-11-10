# SPDX-License-Identifier: MIT
import sys

from atlas_reviewer.cli import main
from atlas_reviewer.stops import install_interrupts

install_interrupts()
sys.exit(main())
