Since you are stepping into the Tech Lead role, setting up the source control (GitHub) properly is one of the most important things you can do. You want to make sure people can collaborate, but nobody can accidentally overwrite or break the `main` branch.

Since the CEO gave you the login details, here is the exact step-by-step guide on how to set this up professionally:

### Step 1: Log in and Create an "Organization" (Highly Recommended)
If the account the CEO gave you is just a standard user account (e.g., `github.com/titancode-ceo`), you should create a **GitHub Organization**. Organizations are designed for companies and make managing teams much easier.
1. Log into GitHub with the credentials the CEO gave you.
2. In the top right corner, click the **+** icon and select **New organization**.
3. Choose the "Free" plan (it allows private repositories and unlimited collaborators).
4. Name it something like `TitanCode-Tech` or `TitanCode-Inc`. 
5. Add yourself (your personal GitHub username) as an **Owner** of the organization so you don't have to keep logging into the CEO's account.

### Step 2: Create the Backend Repository
1. Inside the new Organization (or the CEO's account if you skipped Step 1), click **New Repository**.
2. Name it `titancode_backend`.
3. Set it to **Private** (very important!).
4. Do **not** initialize it with a README, .gitignore, or license (leave it completely empty, because you already have files on your computer).
5. Click **Create repository**. GitHub will show you a URL like `https://github.com/TitanCode-Inc/titancode_backend.git`. Copy this URL.

### Step 3: Push Your Code to the New Repository
Right now, your local code at `/home/jabs/Code/work/titanCode_backend` is pointing to your personal GitHub. Let's change the "remote" URL so it pushes to the company account instead. Open your terminal and run these commands (replace the URL with the one you copied in Step 2):

```bash
# 1. Remove your personal github from being the default destination
git remote remove origin

# 2. Add the new company repository as the destination
git remote add origin https://github.com/Your-Company-Name/titancode_backend.git

# 3. Push all your code and branches to the new repo
git push -u origin main
```

### Step 4: Invite Your Team Members
Now that the code is there, let's bring the team in securely:
1. Go to the new `titancode_backend` repository in GitHub.
2. Click on **Settings** (top right tab).
3. Click on **Collaborators and teams** on the left menu.
4. Click **Add people**.
5. Enter the GitHub usernames or email addresses of your frontend developers.
6. **Important:** Give them **Write** access (not Admin). This allows them to push code but not delete the repository.

### Step 5: Protect the `main` Branch (Tech Lead Secret Weapon)
You do not want *anyone* (even yourself) pushing broken code directly to the `main` branch. You want them to open a **Pull Request (PR)** so you can review it first.
1. In the repository **Settings**, click on **Branches** on the left menu.
2. Click **Add branch ruleset** (or Add classic branch protection rule).
3. Set the target branch name to `main`.
4. Check the box for **Require a pull request before merging**.
5. Check the box for **Require approvals** (set it to 1).
6. Click **Create** or **Save changes**.

By doing this, whenever a frontend dev finishes a task, they have to submit a Pull Request. You will get a notification, you can look at their code, and click "Approve" before it gets merged into the main project. 

Let me know once you get logged into the CEO's account, and I can help you run the terminal commands to push the code up!