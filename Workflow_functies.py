import csv
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import warnings

import matplotlib.pyplot as plt
import nbconvert
import nbgrader
import numpy as np
import pandas as pd
import pickle
import seaborn as sns
from bs4 import BeautifulSoup
from canvasapi import Canvas
from IPython.display import Javascript, Markdown, display
from ipywidgets import (Button, Layout, fixed, interact, interact_manual,
                        interactive, widgets)
from nbgrader.apps import NbGraderAPI
from tqdm import tqdm, tqdm_notebook  # Progress bar
from traitlets.config import Config

warnings.filterwarnings('ignore')

class Course:
    canvas_course = None
    filename = 'workflow.config'    

    sequence = [
        "AssignmentWeek1", "AssignmentWeek2", "AssignmentWeek3", "Deeltoets1",
        "AssignmentWeek5", "AssignmentWeek6", "AssignmentWeek7", "Deeltoets2"
    ]

    def __init__(self):
        if self.filename in os.listdir():
            self.load_pickle()
        else:
            self.gradedict = {}
        if self.canvas_course==None:
            login_button = interact_manual.options(
                manual_name="Inloggen ffs")
            login_button(self.log_in, canvas_id='', url="https://canvas.uva.nl", key = '')

            
        config = Config()
        config.Exchange.course_id = os.getcwd().split('\\')[-1]
        # error
        self.nbgrader_api = NbGraderAPI(config=config)
        
        
    def log_in(self, canvas_id, url, key):
        try:
            self.canvas_course = Canvas(url, key).get_course(int(canvas_id))
        except ValueError:
            print("Course id should be an integer")
        except InvalidAccessToken:
            print("Incorrect key")
        self.save_pickle()
       
        

    # https://stackoverflow.com/questions/2709800/how-to-pickle-yourself
    def load_pickle(self):
        f = open(self.filename, 'rb')
        tmp_dict = pickle.load(f)
        f.close()

        self.__dict__.update(tmp_dict)

    def save_pickle(self):
        f = open(self.filename, 'wb')
        temp = {k:v for k,v in self.__dict__.items () if k!= 'nbgrader_api'} 
        pickle.dump(temp, f, 2)
        f.close()

    def update_db(self):
        assert self.canvas_course != None
        # Check which students are already in nbgrader database
        students_already_in_db = [
            student.id for student in self.nbgrader_api.gradebook.students
        ]

        for student in tqdm_notebook(
                self.canvas_course.get_users(enrollment_type=['student'])):
            first_name, last_name = student.name.split(' ', 1)
            # Add students that are not yet in nbgrader database
            if student.sis_user_id not in students_already_in_db:
                self.nbgrader_api.gradebook.add_student(
                    str(student.sis_user_id),
                    first_name=first_name,
                    last_name=last_name)

    def assign(self, assignment_id):
        submission = True
        file = 'source/' + assignment_id + '/' + assignment_id + ".ipynb"
        assert os.path.exists(
            file), "The folder name and notebook name are not equal."
        subprocess.run(["nbgrader", "update", file])
        #!nbgrader update {file}
        #!nbgrader assign {assignment_id} --create --force --IncludeHeaderFooter.header=source/header.ipynb
        subprocess.run([
            "nbgrader", "assign", assignment_id, "--create", "--force",
            "--IncludeHeaderFooter.header=source/header.ipynb"
        ])
        if self.canvas_course != None:
            assignmentdict = {
                assignment.name: assignment.id
                for assignment in self.canvas_course.get_assignments()
            }

            # If Assignment does not exist, create assignment
            if assignment_id not in assignmentdict.keys():
                if submission:
                    self.canvas_course.create_assignment(
                        assignment={
                            'name': assignment_id,
                            'points_possible': 10,
                            'submission_types': 'online_upload',
                            'allowed_extensions': 'ipynb'
                        })
                else:
                    self.canvas_course.create_assignment(
                        assignment={
                            'name': assignment_id,
                            'points_possible': 10
                        })

    def nbgrader_assignments(self):
        return sorted([
            assignment
            for assignment in self.nbgrader_api.get_source_assignments()
        ])

    def download_files(self, assignment_id):
        if self.canvas_course != None:
            if assignment_id in [
                    assignment.name
                    for assignment in self.canvas_course.get_assignments()
            ]:
                # Get sis id's from students
                student_dict = get_student_ids(self.canvas_course)

                # Get the Canvas assignment id
                assignment = get_assignment_obj(assignment_id)

                for submission in tqdm_notebook(assignment.get_submissions()):
                    # Check if submission has attachments
                    if 'attachments' not in submission.attributes:
                        continue
                    # Download file and give correct name
                    student_id = student_dict[submission.user_id]
                    attachment = submission.attributes["attachments"][0]
                    directory = str(student_id) + "/" + assignment_id + "/"
                    filename = assignment_id + ".ipynb"
                    urllib.request.urlretrieve(attachment['url'],
                                               directory + filename)
                    # Clear all notebooks of output to save memory
                    subprocess.run(["nbstripout", directory + filename])
                    #!nbstripout {directory + filename}
        else:
            print("No assignment found on Canvas")
        # Move the download files to submission folder
        if os.path_exists('downloaded/%s/' % (assignment_id)):
            for file in os.listdir('downloaded/%s/' % (assignment_id)):
                pass
            subprocess.run([
                "nbgrader", "zip_collect", assignment_id, "--force",
                "--log-level='INFO'"
            ])
            #!nbgrader zip_collect {assignment_id} --force --log-level="INFO"

    def get_assignment_obj(self, assignment_name):
        return {
            assignment.name: assignment
            for assignment in self.canvas_course.get_assignments()
        }[assignment_name]

    def autograde(self, assignment_id):
        for student in tqdm_notebook(
                sorted(
                    self.nbgrader_api.get_submitted_students(assignment_id))):
            print("Currently grading: %s" % student)
            student2 = "'" + student + "'"
            subprocess.run([
                "nbgrader", "autograde", assignment_id, "--create", "--force",
                "--quiet", student2
            ])
        display(
            Markdown(
                '<a class="btn btn-primary" style="margin-top: 10px; text-decoration: none;" href="http://localhost:8888/formgrader/gradebook/%s/%s" target="_blank">Klik hier om te manual graden</a>'
                % (assignment_id, assignment_id)))

    def plagiatcheck(self, assignment_id):
        if os.path.exists('plagiaatcheck/%s/' % assignment_id):
            shutil.rmtree(
                'plagiaatcheck/%s/' % assignment_id, ignore_errors=True)
        os.makedirs('plagiaatcheck/%s/pyfiles/' % assignment_id)
        os.makedirs('plagiaatcheck/%s/base/' % assignment_id)

        test = nbconvert.PythonExporter()
        test2 = test.from_filename(
            'release/%s/%s.ipynb' % (assignment_id, assignment_id))
        f = open(
            "plagiaatcheck/%s/base/%s.py" % (assignment_id, assignment_id),
            "w")
        f.write(test2[0])
        f.close()

        for folder in tqdm_notebook(
                self.nbgrader_api.get_submitted_students(assignment_id)):
            test2 = test.from_filename('submitted/%s/%s/%s.ipynb' %
                                       (folder, assignment_id, assignment_id))
            f = open(
                "plagiaatcheck/%s/pyfiles/%s_%s.py" % (assignment_id, folder,
                                                       assignment_id), "w")
            f.write(test2[0])
            f.close()

        if not sys.platform.startswith('win'):
            os.makedirs("plagiaatcheck/%s/html/" % assignment_id)
            subprocess.run([
                "compare50", "plagiaatcheck/{assignment_id}/pyfiles/*", "-d",
                "plagiaatcheck/{assignment_id}/base/", "-o",
                "plagiaatcheck/{assignment_id}/html/"
            ])
        else:
            print("Oeps, voor compare50 heb je Linux of Mac nodig.")
        display(
            Markdown(
                '<a class="btn btn-primary" style="margin-top: 10px; text-decoration: none;" href="plagiaatcheck/%s/" target="_blank">Open map met plagiaatresultaten</a>'
                % assignment_id))

    def color_grades(self, row):
        if row['interval'].right <= 5.5:
            return 'r'
        else:
            return 'g'

    def visualize_grades(self, assignment_id, min_grade, max_score):
        """Creates a plot of the grades from a specific assignment"""
        grades = self.create_grades_per_assignment(assignment_id, min_grade,
                                                   max_score)[assignment_id]
        index = (i["student"]
                 for i in self.nbgrader_api.get_submissions(assignment_id)
                 if i["autograded"])

        grades = grades.reindex(index, axis='index').dropna()
        print("The mean grade is {:.1f}".format(grades.mean()))
        print("The median grade is {}".format(grades.median()))
        print("Maximum van Cohen-Schotanus is {:.1f}".format(
            grades.nlargest(max(5, int(len(grades) * 0.05))).mean()))
        print("Het percentage onvoldoendes is {:.1f}%. ".format(
            100 * sum(grades < 5.5) / len(grades)))
        if 100 * sum(grades < 5.5) / len(grades) > 30:
            print(
                "Het percentage onvoldoendes is te hoog, voor meer informatie kijk op: {}"
                .format(
                    "http://toetsing.uva.nl/toetscyclus/analyseren/tentamenanalyse/tentamenanalyse.html#anker-percentage-geslaagde-studenten"
                ))
        sns.set(style="darkgrid")
        bins = np.arange(1, 10, 0.5)
        interval = [pd.Interval(x, x + 0.5, closed='left') for x in bins]
        interval[-1] = pd.Interval(left=9.5, right=10.001, closed='left')
        interval = pd.IntervalIndex(interval)
        new_grades = grades.groupby([pd.cut(grades, interval)]).size()
        test_grades = pd.DataFrame(new_grades)
        test_grades.columns = ["Test"]
        test_grades = test_grades.reset_index()
        test_grades.columns = ["interval", "Test"]
        test_grades['color'] = test_grades.apply(self.color_grades, axis=1)
        fig, ax = plt.subplots()
        ax.set_xlim(1, 10)
        ax.xaxis.set_ticks(range(1, 11))
        ax2 = ax.twinx()
        ax2.yaxis.set_ticks([])
        ax.bar(
            bins,
            new_grades,
            width=0.5,
            align="edge",
            color=test_grades['color'])
        sns.kdeplot(grades, ax=ax2, clip=(1, 10))

        grades_button = Button(
            description="Save grades", layout=Layout(width='300px'))
        grades_button.on_click(self.update_grades)
        self.curr_assignment = assignment_id
        self.curr_grade_settings = {
            "max_score": max_score,
            "min_grade": min_grade
        }
        display(grades_button)

    def update_grades(self, b):
        self.gradedict[self.curr_assignment] = self.curr_grade_settings
        self.save_pickle()

    def p_value(self, df):
        return df.groupby(
            'question_name', sort=False)['final_score'].mean() / df.groupby(
                'question_name', sort=False)['max_score'].mean()

    def create_grades_per_assignment(self,
                                     assignment_name,
                                     min_grade=None,
                                     max_score=None):
        canvasdf = pd.DataFrame(
            self.nbgrader_api.gradebook.submission_dicts(
                assignment_name)).set_index('student')
        if min_grade == None and max_score == None:
            min_grade, max_score, _ = self.get_default_grade(assignment_name)

        canvasdf['grade'] = canvasdf['score'].apply(
            lambda row: self.calculate_grade(row, min_grade, max_score))
        canvasdf = canvasdf.pivot_table(
            values='grade', index='student', columns='name', aggfunc='first')
        return canvasdf

    def total_df(self):

        canvasdf = pd.concat([
            self.create_grades_per_assignment(x)
            for x in self.graded_submissions()
        ],
                             axis=1)
        return canvasdf

    def calculate_grade(self, score, min_grade, max_score):
        """Calculate grade for an assignment"""
        return max(
            1,
            min(
                round(min_grade + (10 - min_grade) * score / max_score, 1),
                10.0))

    def graded_submissions(self):
        return [
            x['name'] for x in self.nbgrader_api.get_assignments()
            if x['num_submissions'] > 0
        ]

    def create_results_per_question(self):
        q = '''
            SELECT
                submitted_assignment.student_id,
                grade_cell.name AS question_name,
                grade_cell.max_score,
                grade.needs_manual_grade AS needs_grading,
                grade.auto_score,
                grade.manual_score,
                grade.extra_credit,
                assignment.name AS assignment
            FROM grade
                INNER JOIN submitted_notebook ON submitted_notebook.id = grade.notebook_id
                INNER JOIN submitted_assignment ON submitted_assignment.id = submitted_notebook.assignment_id
                INNER JOIN grade_cell ON grade_cell.id = grade.cell_id
                INNER JOIN assignment ON submitted_assignment.assignment_id = assignment.id
        '''

        df = pd.read_sql_query(q, 'sqlite:///gradebook.db')

        df['final_score'] = np.where(
            ~pd.isnull(df['manual_score']), df['manual_score'],
            df['auto_score']) + df['extra_credit'].fillna(0)
        return df.fillna(0)

    def interact_grades(self, assignment_id):

        min_grade, max_score, abs_max = self.get_default_grade(assignment_id)
        interact(
            self.visualize_grades,
            assignment_id=fixed(assignment_id),
            min_grade=widgets.FloatSlider(
                value=min_grade,
                min=0,
                max=10.0,
                step=0.5,
                continuous_update=False),
            max_score=widgets.FloatSlider(
                value=max_score,
                min=1,
                max=abs_max,
                step=0.5,
                continuous_update=False))

    def get_default_grade(self, assignment_id):
        canvasdf = pd.DataFrame(
            self.nbgrader_api.gradebook.submission_dicts(
                assignment_id)).set_index('student')
        abs_max = canvasdf['max_score'].max()
        if assignment_id in self.gradedict.keys():
            if "max_score" in self.gradedict[assignment_id].keys():
                max_score = self.gradedict[assignment_id]["max_score"]
            else:
                max_score = canvasdf['max_score'].max()
            if "min_grade" in self.gradedict[assignment_id].keys():
                min_grade = self.gradedict[assignment_id]["min_grade"]
            else:
                min_grade = 0

        else:
            max_score = abs_max
            min_grade = 0
        return min_grade, max_score, abs_max

    def question_visualizations(self, assignment_id):
        df = self.create_results_per_question()
        df = df.loc[df['assignment'] == assignment_id]
        df = df[df['max_score'] > 0]  # dit kan mooier pretty sure
        p_df = self.p_value(df)
        rir_df = self.create_rir(df)
        combined_df = pd.concat([p_df, rir_df], axis=1)
        combined_df = combined_df.reindex(list(p_df.index))
        combined_df = combined_df.reset_index()
        combined_df.columns = ["Question", "P value", "Rir value", "positive"]

        sns.set(style="darkgrid")
        fig, axes = plt.subplots(1, 2, figsize=(12, 7), sharey=True)
        plt.suptitle('P value and Rir value per question')
        sns.barplot(
            x="P value", y="Question", data=combined_df, color='b',
            ax=axes[0]).set_xlim(0, 1.0)
        sns.barplot(
            x="Rir value",
            y="Question",
            data=combined_df,
            ax=axes[1],
            palette=combined_df["positive"]).set_xlim(-1.0, 1.0)

    def f(self, row):
        if row['Rir-waarde'] <= 0:
            return 'r'
        elif row['Rir-waarde'] <= 0.25:
            return 'y'
        else:
            return 'g'

    def create_rir(self, df):
        testdict = {}

        if len(df["student_id"].unique()) < 50:
            print("Norm of 50 students not reached to be meaningful")

        df["total_score_item"] = df["extra_credit"] + df["auto_score"] + df[
            "manual_score"]
        df['student_score-item'] = df['total_score_item'].groupby(
            df['student_id']).transform('sum') - df['total_score_item']
        for question in sorted(set(df["question_name"].values)):
            temp_df = df.loc[df['question_name'] == question]
            testdict[question] = temp_df[[
                "total_score_item", "student_score-item"
            ]].corr().iloc[1, 0]
        testdf = pd.DataFrame.from_dict(
            testdict, orient='index', columns=["Rir-waarde"])
        testdf['positive'] = testdf.apply(self.f, axis=1)
        return testdf

    def create_overview(self, df):
        df = df.fillna(0)
        testlist = []
        l = [x for x in self.sequence if x in df.columns]

        for n, c in enumerate(l):

            kolommen_assignments = set(
                [x for x in l[:n + 1] if x.startswith("AssignmentWeek")])
            kolommen_deeltoets = set(
                [x for x in l[:n + 1] if x.startswith("Deeltoets")])
            temp = df[df[c] > 0]
            if kolommen_deeltoets == set():
                voldoende_deeltoets = pd.Series(
                    [True for x in range(len(df.index))], index=df.index)
            else:
                voldoende_deeltoets = temp[kolommen_deeltoets].mean(
                    axis=1) >= 5.5
            voldoende_assignments = temp[kolommen_assignments].mean(
                axis=1) >= 5.5
            testlist.append(
                [c] + [len(df) - len(temp)] +
                [(x & y).sum()
                 for x in [~voldoende_deeltoets, voldoende_deeltoets]
                 for y in [~voldoende_assignments, voldoende_assignments]])

        testdf = pd.DataFrame(
            testlist,
            columns=[
                "Assignment Name", "Heeft niet meegedaan aan deze opdracht",
                "Onvoldoende voor beide onderdelen",
                "Onvoldoende voor deeltoets", "Onvoldoende voor assignments",
                "Voldoende voor beide onderdelen"
            ]).set_index("Assignment Name")
        return testdf

    def visualize_overview(self):
        df = self.total_df()
        overviewdf = self.create_overview(df)

        fig, axes = plt.subplots(2, 1, figsize=(12, 12), sharex=True)
        sns.set(style="darkgrid")
        plt.suptitle('Overview of the course')
        df = df.reindex([x for x in self.sequence if x in df.columns], axis=1)
        a = sns.boxplot(data=df.mask(df < 1.0), ax=axes[0])
        a.set_title('Boxplot for each assignment')
        a.set_ylim(1, 10)
        sns.despine()
        flatui = ["#808080", "#FF0000", "#FFA500", "#FFFF00", "#008000"]
        sns.set_palette(flatui)
        b = overviewdf.plot.bar(
            stacked=True,
            color=flatui,
            ylim=(0, overviewdf.sum(axis=1).max()),
            width=1.0,
            legend='reverse',
            ax=axes[1])
        b.set_title(
            'How many students have suifficient grades to pass after that assignment'
        )
        plt.xticks(rotation=45)
        plt.legend(
            loc='right',
            bbox_to_anchor=(1.4, 0.8),
            fancybox=True,
            shadow=True,
            ncol=1)
        
    def upload_button(self):
        if self.canvas_course== None:
            print("Credentials for Canvas were not provided, therefore it is impossible to upload.")
            return
        canvas_button = interact_manual.options(
            manual_name="Cijfers naar Canvas jwz")
        canvas_button(
            self.upload_to_canvas,
            assignment_name=self.canvas_and_nbgrader());

    def upload_to_canvas(self, assignment_name, message='', feedback=False):
        print(feedback, assignment_name, message)
        if feedback:
            subprocess.run([
                "nbgrader", "feedback", "--quiet", "--force",
                "--assignment=%s" % assignment_name
            ])

        # Haal de laatste cijfers uit gradebook
        canvasdf = self.total_df()
        student_dict = self.get_student_ids()

        assignment = self.get_assignment_obj(assignment_name)
        # loop over alle submissions voor een assignment, alleen als er attachments zijn
        for submission in tqdm_notebook(
                assignment.get_submissions(), desc='Submissions', leave=False):
            try:
                student_id = student_dict[submission.user_id]
            except Exception as e:
                continue
            if student_id not in list(canvasdf.index.values):
                continue
            grade = canvasdf.at[student_id, assignment_name]
            if np.isnan(grade):
                continue
            # alleen de cijfers veranderen als die op canvas lager zijn of niet bestaan
            if submission.attributes[
                    'score'] != grade and submission.attributes['score'] != 0:
                if feedback:
                    feedbackfile = create_feedback(student_id, assignment_name)
                    submission.upload_comment(feedbackfile)
                submission.edit(
                    submission={'posted_grade': str(grade)},
                    comment={'text_comment': message})

        # feedbackfile verwijderen, om ruimte te besparen.
        if 'canvasfeedback' in os.listdir():
            shutil.rmtree('canvasfeedback/', ignore_errors=True)
        if 'feedback' in os.listdir():
            shutil.rmtree('feedback/', ignore_errors=True)

    def get_student_ids(self):
        return {
            student.id: student.sis_user_id
            for student in self.canvas_course.get_users()
        }

    def visualize_validity(self):
        canvas_grades = self.total_df()
        cronbach_df = self.cronbach_alpha_plot()
        fig, axes = plt.subplots(1, 2, figsize=(15, 7))
        sns.set(style="darkgrid")
        a = sns.heatmap(
            canvas_grades.corr(),
            vmin=-1,
            vmax=1.0,
            annot=True,
            linewidths=.5,
            cmap="RdYlGn",
            ax=axes[0])
        a.set_title("Correlations between assignments")
        a.set(ylabel='', xlabel='')

        b = sns.barplot(
            y="Assignment",
            x="Cronbachs Alpha",
            data=cronbach_df,
            palette=map(self.color_ca_plot, cronbach_df["Cronbachs Alpha"]),
            ax=axes[1])
        b.set_xlim(0, 1.0)
        b.set(ylabel='')
        b.set_title("Cronbachs Alpha for each assignment")

    def create_feedback(self, student_id, assignment_id):
        """Given a student_id and assignment_id, creates a feedback file without the Hidden Tests"""
        directory = 'feedback/%s/%s/' % (student_id, assignment_id)
        soup = str(
            BeautifulSoup(
                open(
                    "%s%s.html" % (directory, assignment_id),
                    encoding='utf-8'), "html.parser"))
        css, html = soup.split('</head>', 1)
        html = re.sub(
            r'(<div class="output_subarea output_text output_error">\n<pre>\n)(?:(?!<\/div>)[\w\W])*(<span class="ansi-red-intense-fg ansi-bold">[\w\W]*?<\/pre>)',
            r'\1\2', html)
        html = re.sub(
            r'<span class="c1">### BEGIN HIDDEN TESTS<\/span>[\w\W]*?<span class="c1">### END HIDDEN TESTS<\/span>',
            '', html)
        soup = css + '</head>' + html
        targetdirectory = 'canvasfeedback/%s/%s/' % (student_id, assignment_id)
        if not os.path.exists(targetdirectory):
            os.makedirs(targetdirectory)
        filename = "%s%s.html" % (targetdirectory, assignment_id)
        Html_file = open(filename, "w", encoding="utf8")
        Html_file.write(soup)
        Html_file.close()
        return filename

    def color_ca_plot(self, c):
        pal = sns.color_palette("RdYlGn_r", 6)
        if c >= 0.8:
            return pal[0]
        elif c >= 0.6:
            return pal[1]
        else:
            return pal[5]

    def cronbach_alpha_plot(self):
        testlist = []
        df = pd.pivot_table(
            self.create_results_per_question(),
            values='final_score',
            index=['student_id'],
            columns=['assignment', 'question_name'],
            aggfunc=np.sum)

        for assignment_id in sorted(set(df.columns.get_level_values(0))):
            items = df[assignment_id].dropna(how='all').fillna(0)

            # source: https://github.com/anthropedia/tci-stats/blob/master/tcistats/__init__.py
            items_count = items.shape[1]
            variance_sum = float(items.var(axis=0, ddof=1).sum())
            total_var = float(items.sum(axis=1).var(ddof=1))

            testlist.append((assignment_id,
                             (items_count / float(items_count - 1) *
                              (1 - variance_sum / total_var))))

        cronbach_df = pd.DataFrame(
            testlist, columns=["Assignment", "Cronbachs Alpha"])
        return cronbach_df

    def canvas_and_nbgrader(self):
        canvas = set(assignment.name
                     for assignment in self.canvas_course.get_assignments())
        nbgrader = set(
            assignment
            for assignment in self.nbgrader_api.get_source_assignments())
        return sorted(canvas & nbgrader)

    def TurnToUvaScores(self, s):
        UvA = round(2 * s + 1) - 1 if int(2 * s) % 2 == 0 else round(2 * s)
        UvA = 0.5 * UvA
        if s >= 4.75 and s <= 5.4999: UvA = 5
        if UvA == 5.5: UvA = 6
        return UvA

    def NAV(self, row):
        if row.Toetsen < 5 or row.Assignments < 5.5 or row.Totaal < 5.5:
            return 0
        else:
            return row["Totaal"]

    def final_grades(self):
        if self.canvas_course== None:
            print("This function only works with Canvas.")
            return
        student_dict = self.get_student_ids()

        test = {
            i.name: {
                student_dict[j.user_id]: j.grade
                for j in i.get_submissions() if j.user_id in student_dict
            }
            for i in self.canvas_course.get_assignments()
        }

        test2 = pd.DataFrame.from_dict(test, orient='columns').astype(float)
        dict_of_weights = {}
        for i in self.canvas_course.get_assignment_groups():
            if i.group_weight > 0:
                dict_of_weights[i.name] = i.group_weight
                assignments = [
                    l.name for l in self.canvas_course.get_assignments()
                    if l.assignment_group_id == i.id
                ]
                test2[i.name] = test2[assignments].fillna(0).mean(axis=1)
        dict_of_weights = {
            x: y / sum(dict_of_weights.values())
            for x, y in dict_of_weights.items()
        }
        test2 = test2[dict_of_weights.keys()]
        l = sns.pairplot(test2, kind="reg")
        for t in l.axes[:, :]:
            for v in t:
                v.set_ylim(1, 10)
                v.set_xlim(1, 10)

        test2["Totaal"] = 0
        for k, v in dict_of_weights.items():
            test2["Totaal"] += test2[k] * v
        test2["Totaal"] = test2["Totaal"].map(self.TurnToUvaScores)
        test2["TotaalNAV"] = test2.apply(lambda row: self.NAV(row), axis=1)

        test2["cat"] = test2.TotaalNAV > 0
        test2["nieuwTotaal"] = test2.Totaal

        test3 = test2.pivot_table(
            index='Totaal',
            columns='cat',
            values='nieuwTotaal',
            aggfunc=np.size)
        test3.plot(kind='bar', stacked=True, width=1)