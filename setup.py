import setuptools

with open("README.md", "r") as fh:

    long_description = fh.read()

setuptools.setup(

     name='workflow_uva',  

     version='0.1',

     scripts=['workflow_uva'] ,

     author="Jasper van der Heide",

     author_email="jaspervdh96@hotmail.com",

     description="A workflow for Canvas and Nbgrader",

     long_description=long_description,

   long_description_content_type="text/markdown",

     url="https://github.com/jaspervdh96/Workflow",

     packages=setuptools.find_packages(),

     classifiers=[

         "Programming Language :: Python :: 3",
         "Operating System :: OS Independent"

     ],

 )
