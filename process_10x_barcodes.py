#!/usr/bin/env python

# Caleb Lareau, Stanford University
# Implemented: 14 November 2020
# This program will error correct barcodes
# From 10x sequencing data from scATAC

##### IMPORT MODULES #####
import os
import re
import regex
import sys
import gzip
import itertools

from optparse import OptionParser
from multiprocessing import Pool, freeze_support
from itertools import repeat

from Bio import SeqIO
from Bio.SeqIO.QualityIO import FastqGeneralIterator

from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from fuzzysearch import find_near_matches

#### OPTIONS ####
opts = OptionParser()
usage = "usage: %prog [options] [inputs] Software to process raw .fastq reads and make data suitable for downstream processes"

opts.add_option("-a", "--fastq1", help="<Read1> Accepts fastq.gz")
opts.add_option("-b", "--fastq2", help="<Read2> Accepts fastq.gz")
opts.add_option("-c", "--fastq3", help="<Read3> Accepts fastq.gz")
opts.add_option("-f", "--barcodesFile", help="<gzip of the universe of valid barcodes to check")

opts.add_option("-n", "--nreads", default = 10000000, help="Number of reads to process in a given chunk")
opts.add_option("-r", "--ncores", default = 8, help="Number of cores for parallel processing.")

opts.add_option("-o", "--output", help="Output sample convention")

options, arguments = opts.parse_args()


# return usage information if no argvs given
if len(sys.argv)==1:
	os.system(sys.argv[0]+" --help")
	sys.exit()


# Define barcodes
barcodesfilepath = options.barcodesFile
with gzip.open(barcodesfilepath, "rt") as my_file:
	barcodesR = my_file.readlines()
barcodes = [barcode.rstrip() for barcode in barcodesR]
print("Found and imported " + str(len(barcodes)) + " barcodes")	
global barcodes_set 
barcodes_set = set(barcodes)

def batch_iterator(iterator, batch_size):
	"""
	Returns lists of tuples of length batch_size.
	"""
	entry = True  # Make sure we loop once
	while entry:
		batch = []
		while len(batch) < batch_size:
			try:
				entry = iterator.__next__()
			except StopIteration:
				entry = None
			if entry is None:
				# End of file
				break
			batch.append(entry)
		if batch:
			yield batch


def chunk_writer_gzip(filename, what):
	'''
	Basic function to write a chunk of a fastq file
	to a gzipped file
	'''
	with gzip.open(filename, 'wt') as out_write:
				out_write.writelines(what)
	return(filename)			

def prove_barcode_simple(bc, valid_set):
	'''
	Function that takes a putative barcode and returns the nearest valid one
	'''
		
	if(bc in valid_set):
		return(bc)
	else:
		return("NA")

			
def formatRead(title, sequence, quality):
	"""
	Takes three components of fastq file and stiches them together in a string
	"""
	return("@%s\n%s\n+\n%s\n" % (title, sequence, quality))


#-----
# This code is modified from CellRanger-ATAC but I'm too lazy to factor in base qualities
# https://github.com/10XGenomics/cellranger-atac/blob/main/mro/atac/stages/processing/attach_bcs/__init__.py
#-----
DNA_ALPHABET = 'AGCT'
ALPHABET_MINUS = {char: {c for c in DNA_ALPHABET if c != char} for char in DNA_ALPHABET}
ALPHABET_MINUS['N'] = set(DNA_ALPHABET)
MAXDIST_CORRECT = 2

def gen_nearby_seqs(seq,wl_idxs, maxdist=3):
	
	allowed_indices = [i for i in range(len(seq)) if seq[i] != 'N']
	required_indices = tuple([i for i in range(len(seq)) if seq[i] == 'N'])
	mindist = len(required_indices)
	if mindist > maxdist:
		return

	for dist in range(mindist + 1, maxdist + 1):
		for modified_indices in itertools.combinations(allowed_indices, dist - mindist):
			indices = set(modified_indices + required_indices)

			for substitutions in itertools.product(
					*[ALPHABET_MINUS[base] if i in indices else base for i, base in enumerate(seq)]):
				new_seq = ''.join(substitutions)
				if new_seq in barcodes_set:
					yield new_seq
					
#------ 

def correct_barcode(seq, maxdist=2):

	if seq in barcodes_set:
		return seq

	for test_str in gen_nearby_seqs(seq, maxdist):
		return(test_str)

	return "N"*16

	
def debarcode_trio(trio):
	"""
	Function that is called in parallel
	"""
	# Parse out inputs
	listRead1 = trio[0]; listRead2 = trio[1]; listRead3 = trio[2]
	
	# parameters to return
	fq1 = ""
	fq2 = ""
	
	# Grab attributes
	title1 = listRead1[0]; sequence1 = listRead1[1]; quality1 = listRead1[2]
	title2 = listRead2[0]; sequence2 = listRead2[1]; quality2 = listRead2[2]
	title3 = listRead3[0]; sequence3 = listRead3[1]; quality3 = listRead3[2]

	corrected_barcode = correct_barcode(sequence2)
	#if(corrected_barcode != sequence2):
	#	print("was " + sequence2 + "   now: " + corrected_barcode)
	
	# Return the barcode with underscores + the biological sequence learned
	ofq1 = formatRead(corrected_barcode + "_" + title1, sequence1, quality1)
	ofq2 = formatRead(corrected_barcode + "_" + title3, sequence3, quality3)
	return(ofq1, ofq2)


if __name__ == "__main__":

	

	##### INPUTS #####
	af = options.fastq1
	bf = options.fastq2
	cf = options.fastq3

	outname = options.output
	o = options.output
	cpu = int(options.ncores)
	n = int(options.nreads)

	# Parse input files
	extension = af.split('.')[-1]
	if extension == "fastq" or extension == "fq":
		sys.exist("Quitting... GZIP your .fastq files!")
	elif extension == "gz":
		print("Found supplied .fastq.gz files")
	else:
		sys.exit("ERROR! The input files (-a , -b, -c) a *.fastq.gz")
	print(options)
	with gzip.open(af, "rt") as f1:
		with gzip.open(bf, "rt") as f2:
				with gzip.open(cf, "rt") as f3:

					# Establish iterators
					it1 = batch_iterator(FastqGeneralIterator(f1), n)
					it2 = batch_iterator(FastqGeneralIterator(f2), n)
					it3 = batch_iterator(FastqGeneralIterator(f3), n)

					# iterate over batches of length n
				
					for i, batch1 in enumerate(it1):
						batch2 = it2.__next__()
						batch3 = it3.__next__()
						output = o 
			
						# parallel process the barcode processing and accounting of failures.
						pool = Pool(processes=cpu)
						pm = pool.map(debarcode_trio, zip(batch1, batch2, batch3))
						pool.close()
			
						# Aggregate output
						fastq1 = [item[0] for item in pm]
						fastq2 = [item[1] for item in pm]

						# Export one chunk in parallel
						filename1 = output +'_R1.fastq.gz'
						filename2 = output +'_R2.fastq.gz'
			
						pool = Pool(processes=2)
						toke = pool.starmap(chunk_writer_gzip, [(filename1, fastq1), (filename2, fastq2)])
						pool.close()
			
	